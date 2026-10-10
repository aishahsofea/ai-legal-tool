import pytest
from fastapi.testclient import TestClient

from api import main

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}


@pytest.mark.parametrize(
    "configured,expected",
    [
        (None, ["http://localhost:3000"]),
        ("", ["http://localhost:3000"]),
        (" , ", ["http://localhost:3000"]),
        ("https://app.example.com", ["https://app.example.com"]),
        ("https://app.example.com/, http://localhost:3000 ", ["https://app.example.com", "http://localhost:3000"]),
    ],
)
def test_allowed_origins_parse_the_env_var(monkeypatch, configured, expected):
    if configured is None:
        monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("FRONTEND_ORIGIN", configured)
    assert main._allowed_origins() == expected


def test_allowed_origins_never_include_a_wildcard(monkeypatch):
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    assert "*" not in main._allowed_origins()


def test_allowed_origin_gets_the_header():
    with TestClient(main.app) as client:
        response = client.options("/query", headers={"Origin": "http://localhost:3000", **PREFLIGHT})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_other_origin_does_not():
    with TestClient(main.app) as client:
        response = client.options("/query", headers={"Origin": "https://evil.example", **PREFLIGHT})
        health = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in health.headers
