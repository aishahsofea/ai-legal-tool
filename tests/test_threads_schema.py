import logging

from fastapi.testclient import TestClient

from api import main, threads_store
from api.threads_store import ensure_schema as real_ensure_schema


class FakeConnection:
    def close(self):
        pass


def test_ensure_schema_applies_the_migration(monkeypatch):
    connection = FakeConnection()
    applied = []
    monkeypatch.setattr(threads_store, "_connect", lambda: connection)
    monkeypatch.setattr(threads_store, "apply_migration", applied.append)

    real_ensure_schema()

    assert applied == [connection]


def test_ensure_schema_logs_and_continues_when_the_database_is_down(monkeypatch, caplog):
    def refuse():
        raise OSError("connection refused")

    monkeypatch.setattr(threads_store, "_connect", refuse)

    with caplog.at_level(logging.ERROR, logger=threads_store.logger.name):
        real_ensure_schema()

    assert "threads schema unavailable" in caplog.text


def test_lifespan_runs_ensure_schema(monkeypatch):
    calls = []
    monkeypatch.setattr(threads_store, "ensure_schema", lambda: calls.append(1))
    with TestClient(main.app):
        pass
    assert calls == [1]
