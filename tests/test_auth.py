import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api import auth

SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "test-key"
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
HS_SECRET = "legacy-secret-at-least-32-bytes-long!!"

app = FastAPI()


@app.get("/me")
def me(user_id: str = Depends(auth.current_user_id)):
    return {"user_id": user_id}


def _jwks():
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
    return {"keys": [{**jwk, "kid": KID, "alg": "ES256", "use": "sig"}]}


def _token(key=PRIVATE_KEY, algorithm="ES256", headers=None, **overrides):
    claims = {"sub": "user-a", "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 600}
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": KID} if headers is None else headers)


@pytest.fixture(autouse=True)
def supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: _jwks())
    auth._jwks_client.cache_clear()
    yield
    auth._jwks_client.cache_clear()


def _get(token=None):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    return TestClient(app).get("/me", headers=headers)


def test_valid_jwks_token_returns_its_subject():
    response = _get(_token())
    assert response.status_code == 200
    assert response.json() == {"user_id": "user-a"}


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not-a-jwt",
        _token(exp=int(time.time()) - 10),
        _token(aud="anon"),
        _token(iss="https://other.supabase.co/auth/v1"),
        _token(sub=None),
        _token(key=OTHER_KEY),
        _token(headers={"kid": "unknown"}),
    ],
    ids=["missing", "malformed", "expired", "wrong-audience", "wrong-issuer", "no-subject", "wrong-key", "unknown-kid"],
)
def test_bad_tokens_are_401(token):
    response = _get(token)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_non_bearer_scheme_is_401():
    response = TestClient(app).get("/me", headers={"Authorization": f"Basic {_token()}"})
    assert response.status_code == 401


def test_hs256_token_is_refused_without_the_legacy_secret():
    assert _get(_token(key=HS_SECRET, algorithm="HS256", headers={})).status_code == 401


def test_hs256_token_is_accepted_with_the_legacy_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", HS_SECRET)
    response = _get(_token(key=HS_SECRET, algorithm="HS256", headers={}))
    assert response.status_code == 200
    assert response.json() == {"user_id": "user-a"}


def test_hs256_token_with_the_wrong_secret_is_401(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", HS_SECRET)
    assert _get(_token(key="wrong-secret-that-is-also-32-bytes!!", algorithm="HS256", headers={})).status_code == 401


def test_jwks_outage_is_503_not_401(monkeypatch):
    def unreachable(self):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", unreachable)
    assert _get(_token()).status_code == 503
