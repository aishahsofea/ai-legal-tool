from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from api.main import app
from reference_graph.store import GraphNotIndexed, GraphUnavailable


def test_reference_graph_is_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("REFERENCE_GRAPH_ENABLED", raising=False)
    response = TestClient(app).get("/reference-graph/status")
    assert response.status_code == 200
    assert response.json()["status"] == "flag-off"


def test_reference_graph_neighborhood_is_one_hop_and_does_not_affect_health(monkeypatch):
    class Store:
        def status(self, document_id):
            return {"status": "available", "document_id": document_id, "counts": {"edges": 1}, "document": {}}

        def neighborhood(self, document_id, focus):
            return {"status": "available", "document_id": document_id, "focus_provision_id": focus,
                    "nodes": [{"provision_id": focus}], "edges": [{"source_provision_id": focus, "target_provision_id": "act:265/section:4"}]}

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    client = TestClient(app)
    result = client.get("/reference-graph/neighborhood", params={"document_id": "act-265-reprint-2023-6fec2f07", "focus_provision_id": "act:265/section:60D"})
    assert result.status_code == 200
    assert result.json()["status"] == "available"
    assert len(result.json()["edges"]) == 1
    assert client.get("/health").json() == {"status": "ok"}


def test_reference_graph_reports_a_snapshot_that_is_not_indexed(monkeypatch):
    class Store:
        def status(self, _document_id):
            raise GraphNotIndexed()

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "on")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    response = TestClient(app).get("/reference-graph/status")
    assert response.json() == {"status": "not_indexed", "document_id": "act-265-reprint-2023-6fec2f07"}


def test_reference_graph_returns_graph_unavailable_without_breaking_health(monkeypatch):
    class Store:
        def status(self, _document_id):
            raise GraphUnavailable("invalid artifact")

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "true")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    client = TestClient(app)
    assert client.get("/reference-graph/status").json()["status"] == "graph_unavailable"
    assert client.get("/health").json() == {"status": "ok"}


def test_reference_graph_and_health_do_not_start_chat_runtime(monkeypatch):
    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    with patch("api.main._AgentRuntime.ensure_started", new=AsyncMock(side_effect=AssertionError("chat runtime started"))) as start:
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/reference-graph/status").json()["status"] in {"available", "not_indexed"}
    start.assert_not_awaited()
