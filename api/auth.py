"""Supabase access-token verification for FastAPI routes (ADR 0022)."""

from __future__ import annotations

import os
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_AUDIENCE = "authenticated"
_bearer = HTTPBearer(auto_error=False)


def _auth_url() -> str:
    return f"{os.environ['SUPABASE_URL'].rstrip('/')}/auth/v1"


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{_auth_url()}/.well-known/jwks.json")


def _signing_key(token: str) -> tuple[object, list[str]]:
    # Branching on the header is safe: each branch pins its own algorithms, so an HS256 token can't be checked against a public key.
    if jwt.get_unverified_header(token).get("alg") == "HS256":
        secret = os.getenv("SUPABASE_JWT_SECRET")
        if not secret:
            raise jwt.InvalidTokenError("HS256 token but SUPABASE_JWT_SECRET is unset")
        return secret, ["HS256"]
    return _jwks_client().get_signing_key_from_jwt(token).key, ["ES256", "RS256"]


def verify_token(token: str) -> str:
    """Return the token's user id, or raise jwt.PyJWTError."""
    key, algorithms = _signing_key(token)
    claims = jwt.decode(
        token,
        key,
        algorithms=algorithms,
        audience=_AUDIENCE,
        issuer=_auth_url(),
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    return claims["sub"]


def current_user_id(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    unauthorized = HTTPException(401, "Invalid or missing access token", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        return verify_token(credentials.credentials)
    except jwt.PyJWKClientConnectionError as exc:
        # A JWKS outage is ours, not the caller's: a 401 would make the frontend sign them out.
        raise HTTPException(503, "Could not reach the auth key set") from exc
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
