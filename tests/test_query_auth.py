from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from api import auth, main

ROUTES = [
    ("/query", {"query": "What is section 5?", "thread_id": "t1"}),
    ("/resume", {"thread_id": "t1", "value": "Contracts Act 1950"}),
    ("/cancel", {"thread_id": "t1"}),
]


class FakeThreads:
    def __init__(self):
        self.owners: dict[str, str] = {}

    def claim_thread(self, thread_id, user_id, title):
        return self.owners.setdefault(thread_id, user_id) == user_id

    def owns(self, thread_id, user_id):
        return self.owners.get(thread_id) == user_id


def _token_is_user(credentials: HTTPAuthorizationCredentials | None = Depends(auth._bearer)) -> str:
    return credentials.credentials


@pytest.fixture
def threads(monkeypatch):
    fake = FakeThreads()
    monkeypatch.setattr(main.threads_store, "claim_thread", fake.claim_thread)
    monkeypatch.setattr(main.threads_store, "owns", fake.owns)
    return fake


@pytest.fixture
def streamed(monkeypatch):
    calls = []

    async def fake_stream(query, thread_id, user_id, *, resume=None, persist=False):
        calls.append({"query": query, "thread_id": thread_id, "user_id": user_id, "persist": persist})
        yield {"type": "response", "content": "ok", "citations": [], "violations": []}

    monkeypatch.setattr(main, "run_query_stream", fake_stream)
    return calls


@pytest.fixture
def client():
    with patch("api.main._AgentRuntime.ensure_started", new=AsyncMock()), TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


@pytest.fixture
def as_users(client):
    main.app.dependency_overrides[auth.current_user_id] = _token_is_user
    return lambda user: {"Authorization": f"Bearer {user}"}


@pytest.mark.parametrize("path,body", ROUTES, ids=[path for path, _ in ROUTES])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}], ids=["missing", "bad"])
def test_routes_refuse_a_missing_or_bad_token(monkeypatch, client, threads, streamed, path, body, headers):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 401
    assert streamed == [] and threads.owners == {}


def test_query_runs_as_the_token_user_not_the_body_user(as_users, client, threads, streamed):
    response = client.post(
        "/query", json={"query": "What is section 5?", "thread_id": "t1", "user_id": "mallory"}, headers=as_users("alice")
    )
    assert response.status_code == 200
    assert streamed == [{"query": "What is section 5?", "thread_id": "t1", "user_id": "alice", "persist": True}]
    assert threads.owners == {"t1": "alice"}


def test_resume_runs_as_the_token_user(as_users, client, threads, streamed):
    threads.owners["t1"] = "alice"
    response = client.post(
        "/resume", json={"thread_id": "t1", "value": "Contracts Act 1950", "user_id": "mallory"}, headers=as_users("alice")
    )
    assert response.status_code == 200
    assert streamed[0]["user_id"] == "alice"


@pytest.mark.parametrize("path,body", ROUTES, ids=[path for path, _ in ROUTES])
def test_another_users_thread_is_404(as_users, client, threads, streamed, path, body):
    threads.owners["t1"] = "alice"
    response = client.post(path, json=body, headers=as_users("bob"))
    assert response.status_code == 404
    assert streamed == []


def test_cancel_on_an_owned_thread_reports_no_active_run(as_users, client, threads):
    threads.owners["t1"] = "alice"
    response = client.post("/cancel", json={"thread_id": "t1"}, headers=as_users("alice"))
    assert response.json() == {"status": "no_active_run"}
