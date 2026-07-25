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


def test_comparison_requires_both_flags_and_fails_independently(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.delenv("REFERENCE_GRAPH_COMPARISON_ENABLED", raising=False)
    response = client.get("/reference-graph/compare", params={
        "base_document_id": "base",
        "compare_document_id": "compare",
        "focus_provision_id": "act:265/section:4",
    })
    assert response.json()["status"] == "comparison_disabled"
    assert client.get("/reference-graph/snapshots").json() == {
        "status": "comparison_disabled",
        "comparison_enabled": False,
        "snapshots": [],
    }
    assert client.get("/reference-graph/status").json()["status"] in {"available", "not_indexed"}

    monkeypatch.delenv("REFERENCE_GRAPH_ENABLED", raising=False)
    monkeypatch.setenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "1")
    assert client.get("/reference-graph/compare", params={
        "base_document_id": "base",
        "compare_document_id": "compare",
        "focus_provision_id": "act:265/section:4",
    }).json()["status"] == "comparison_disabled"


def test_comparison_rejects_identical_pairs_duplicates_and_unbounded_inputs(monkeypatch):
    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "1")
    client = TestClient(app)
    common = "base_document_id=base&compare_document_id=base&focus_provision_id=act%3A265%2Fsection%3A4"
    assert client.get(f"/reference-graph/compare?{common}").status_code == 422
    duplicated = (
        "base_document_id=base&compare_document_id=compare&compare_document_id=other"
        "&focus_provision_id=act%3A265%2Fsection%3A4"
    )
    assert client.get(f"/reference-graph/compare?{duplicated}").status_code == 422
    with_depth = (
        "base_document_id=base&compare_document_id=compare"
        "&focus_provision_id=act%3A265%2Fsection%3A4&depth=2"
    )
    assert client.get(f"/reference-graph/compare?{with_depth}").status_code == 422
    unsafe = (
        "base_document_id=..%2Fbase&compare_document_id=compare"
        "&focus_provision_id=act%3A265%2Fsection%3A4"
    )
    assert client.get(f"/reference-graph/compare?{unsafe}").status_code == 422


def test_comparison_reports_pair_status_and_observed_counts(monkeypatch, caplog):
    class Store:
        def status(self, document_id):
            if document_id == "missing":
                raise GraphNotIndexed(document_id)
            return {"status": "available", "counts": {}, "document": {}}

        def document(self, _document_id):
            return {"act_number": "265", "language": "en"}

        def compare(self, base, compare, focus):
            return {
                "status": "available",
                "base_document_id": base,
                "compare_document_id": compare,
                "focus_provision_id": focus,
                "counts": {"added": 1, "removed": 2, "unchanged": 3},
                "nodes": [],
                "references": [],
            }

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "1")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    client = TestClient(app)
    params = {
        "base_document_id": "base",
        "compare_document_id": "compare",
        "focus_provision_id": "act:265/section:4",
    }
    caplog.set_level("INFO", logger="api.reference_graph")
    assert client.get("/reference-graph/compare", params=params).json()["counts"] == {
        "added": 1, "removed": 2, "unchanged": 3,
    }
    comparison_log = next(
        record.getMessage() for record in caplog.records
        if "operation=compare" in record.getMessage() and "outcome=available" in record.getMessage()
    )
    assert "base_document_id=base" in comparison_log
    assert "compare_document_id=compare" in comparison_log
    assert "focus=act:265/section:4" in comparison_log
    assert "added=1 removed=2 unchanged=3" in comparison_log
    assert "latency_ms=" in comparison_log
    assert "provision text" not in comparison_log
    params["compare_document_id"] = "missing"
    assert client.get("/reference-graph/compare", params=params).json()["status"] == "not_indexed_compare"
    params["base_document_id"] = "missing"
    params["compare_document_id"] = "compare"
    assert client.get("/reference-graph/compare", params=params).json()["status"] == "not_indexed_base"


def test_comparison_graph_failure_is_isolated_from_phase1_and_health(monkeypatch):
    class Store:
        def status(self, _document_id):
            raise GraphUnavailable("bad comparison artifact")

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "1")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    client = TestClient(app)
    response = client.get("/reference-graph/compare", params={
        "base_document_id": "base",
        "compare_document_id": "compare",
        "focus_provision_id": "act:265/section:4",
    })
    assert response.json()["status"] == "graph_unavailable"
    assert client.get("/reference-graph/status").json()["status"] == "graph_unavailable"
    assert client.get("/health").json() == {"status": "ok"}


def test_comparison_rejects_mismatched_acts_or_languages(monkeypatch):
    class Store:
        def status(self, _document_id):
            return {"status": "available", "counts": {}, "document": {}}

        def document(self, document_id):
            return {
                "act_number": "265" if document_id == "base" else "266",
                "language": "en",
            }

    monkeypatch.setenv("REFERENCE_GRAPH_ENABLED", "1")
    monkeypatch.setenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "1")
    monkeypatch.setattr("api.reference_graph.graph_store", lambda: Store())
    response = TestClient(app).get("/reference-graph/compare", params={
        "base_document_id": "base",
        "compare_document_id": "compare",
        "focus_provision_id": "act:265/section:4",
    })
    assert response.status_code == 422
