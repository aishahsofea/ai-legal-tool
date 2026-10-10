import pytest
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from api import auth, main, threads

RECEIPT = {"document_id": "act-265-en-sha256-" + "a" * 64, "evidence": {"start_page": 37, "quote": "employer shall"}}
CITATION = {"act_number": "265", "section_number": "60A", "receipt": RECEIPT}


class FakeThreads:
    def __init__(self):
        self.threads = {
            "a-old": {"user_id": "alice", "title": "Old", "updated_at": "2026-10-01"},
            "a-new": {"user_id": "alice", "title": "New", "updated_at": "2026-10-02"},
            "b-1": {"user_id": "bob", "title": "Bob's", "updated_at": "2026-10-03"},
        }
        self.turns = {
            "a-new": [
                {"query": "q0", "response": "r0", "citations": [CITATION], "commentary": None, "currency_labels": None},
                {"query": "q1", "response": "r1", "citations": [], "commentary": [{"publisher": "x"}],
                 "currency_labels": [{"label": "in_force"}]},
            ]
        }

    def list_threads(self, user_id):
        rows = [{"id": tid, "title": t["title"], "updated_at": t["updated_at"]}
                for tid, t in self.threads.items() if t["user_id"] == user_id]
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)

    def get_thread(self, thread_id, user_id):
        thread = self.threads.get(thread_id)
        if thread is None or thread["user_id"] != user_id:
            return None
        return {"id": thread_id, "title": thread["title"], "turns": self.turns.get(thread_id, [])}


def _token_is_user(credentials: HTTPAuthorizationCredentials | None = Depends(auth._bearer)) -> str:
    return credentials.credentials


@pytest.fixture(autouse=True)
def store(monkeypatch):
    fake = FakeThreads()
    monkeypatch.setattr(threads.threads_store, "list_threads", fake.list_threads)
    monkeypatch.setattr(threads.threads_store, "get_thread", fake.get_thread)
    return fake


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


@pytest.fixture
def as_user(client):
    main.app.dependency_overrides[auth.current_user_id] = _token_is_user
    return lambda user: {"Authorization": f"Bearer {user}"}


@pytest.mark.parametrize("path", ["/threads", "/threads/a-new"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-jwt"}], ids=["missing", "bad"])
def test_refuses_a_missing_or_bad_token(monkeypatch, client, path, headers):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    assert client.get(path, headers=headers).status_code == 401


def test_lists_only_the_callers_threads_newest_first(client, as_user):
    response = client.get("/threads", headers=as_user("alice"))
    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == ["a-new", "a-old"]


def test_thread_flattens_turns_into_messages_with_receipts_intact(client, as_user):
    body = client.get("/threads/a-new", headers=as_user("alice")).json()
    assert body["title"] == "New"
    assert body["messages"] == [
        {"role": "user", "content": "q0"},
        {"role": "assistant", "content": "r0", "citations": [CITATION], "commentary": [], "currency_labels": []},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "r1", "citations": [], "commentary": [{"publisher": "x"}],
         "currency_labels": [{"label": "in_force"}]},
    ]
    assert body["messages"][1]["citations"][0]["receipt"] == RECEIPT


def test_thread_with_no_completed_turns_has_no_messages(client, as_user):
    assert client.get("/threads/a-old", headers=as_user("alice")).json()["messages"] == []


@pytest.mark.parametrize("thread_id", ["a-new", "missing"], ids=["foreign", "missing"])
def test_foreign_or_missing_thread_is_404(client, as_user, thread_id):
    assert client.get(f"/threads/{thread_id}", headers=as_user("bob")).status_code == 404
