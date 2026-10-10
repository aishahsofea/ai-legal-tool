import os
import uuid
from contextlib import closing

import psycopg2
import pytest

from api import threads_store

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="needs TEST_DATABASE_URL pointing at a disposable Postgres"
)


@pytest.fixture(autouse=True)
def isolated_schema(monkeypatch):
    schema = f"threads_test_{uuid.uuid4().hex}"
    with closing(psycopg2.connect(TEST_DATABASE_URL)) as admin, admin, admin.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA {schema}")

    def connect():
        return psycopg2.connect(TEST_DATABASE_URL, options=f"-c search_path={schema}")

    with closing(connect()) as connection:
        threads_store.apply_migration(connection)
    monkeypatch.setattr(threads_store, "_connect", connect)
    yield
    with closing(psycopg2.connect(TEST_DATABASE_URL)) as admin, admin, admin.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA {schema} CASCADE")


def _citation():
    return {
        "act_number": "265",
        "section_number": "60A",
        "receipt": {"document_id": "act-265-en-sha256-" + "a" * 64, "evidence": {"start_page": 37}},
    }


def test_owner_can_reclaim_but_second_user_is_refused():
    assert threads_store.claim_thread("t1", "alice", "First question")
    assert threads_store.claim_thread("t1", "alice", "Ignored")
    assert not threads_store.claim_thread("t1", "bob", "Hijack")

    assert threads_store.owns("t1", "alice")
    assert not threads_store.owns("t1", "bob")
    assert threads_store.get_thread("t1", "alice")["title"] == "First question"


def test_list_is_newest_first_and_scoped_to_the_user():
    threads_store.claim_thread("older", "alice", "Older")
    threads_store.claim_thread("newer", "alice", "Newer")
    threads_store.claim_thread("other", "bob", "Bob's")
    assert [t["id"] for t in threads_store.list_threads("alice")] == ["newer", "older"]

    threads_store.append_turn("older", "q", "r", [])
    assert [t["id"] for t in threads_store.list_threads("alice")] == ["older", "newer"]
    assert [t["id"] for t in threads_store.list_threads("bob")] == ["other"]


def test_turn_indexes_are_contiguous_and_round_trip():
    threads_store.claim_thread("t1", "alice", "Q0")
    indexes = [
        threads_store.append_turn("t1", f"q{i}", f"r{i}", [_citation()], currency_labels=[{"label": "in_force"}])
        for i in range(3)
    ]
    assert indexes == [0, 1, 2]

    turns = threads_store.get_thread("t1", "alice")["turns"]
    assert [t["turn_index"] for t in turns] == [0, 1, 2]
    assert [t["query"] for t in turns] == ["q0", "q1", "q2"]
    assert turns[0]["citations"] == [_citation()]
    assert turns[0]["currency_labels"] == [{"label": "in_force"}]
    assert turns[0]["commentary"] is None


def test_turn_indexes_are_per_thread():
    threads_store.claim_thread("a", "alice", "A")
    threads_store.claim_thread("b", "alice", "B")
    threads_store.append_turn("a", "q", "r", [])
    assert threads_store.append_turn("b", "q", "r", []) == 0
    assert threads_store.append_turn("a", "q", "r", []) == 1


def test_get_thread_hides_a_foreign_thread():
    threads_store.claim_thread("t1", "alice", "Q")
    assert threads_store.get_thread("t1", "bob") is None
    assert threads_store.get_thread("missing", "alice") is None


def test_append_to_unknown_thread_raises():
    with pytest.raises(LookupError):
        threads_store.append_turn("missing", "q", "r", [])
