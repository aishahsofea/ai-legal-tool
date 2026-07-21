"""Flag-gated, read-only statutory reference-graph endpoints."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Query

from reference_graph.models import GRAPH_DOCUMENT_ID
from reference_graph.store import GraphNotIndexed, GraphUnavailable, ReferenceGraphStore

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix="/reference-graph", tags=["reference-graph"])


def reference_graph_enabled() -> bool:
    """The only source of truth for graph exposure; default safely disabled."""
    return os.getenv("REFERENCE_GRAPH_ENABLED", "").strip().casefold() in {"1", "true", "yes", "on"}


def graph_store() -> ReferenceGraphStore:
    return ReferenceGraphStore(Path(os.getenv("REFERENCE_GRAPH_ROOT", ROOT / "data" / "reference_graph")))


def _record(operation: str, started: float, outcome: str, **fields: Any) -> None:
    logger.info("reference_graph operation=%s outcome=%s latency_ms=%d %s", operation, outcome,
                round((perf_counter() - started) * 1000), " ".join(f"{key}={value}" for key, value in fields.items()))


def _availability(document_id: str, operation: str) -> dict[str, Any]:
    started = perf_counter()
    if not reference_graph_enabled():
        payload = {"status": "flag-off", "document_id": document_id}
        _record(operation, started, "flag-off", document_id=document_id)
        return payload
    try:
        payload = graph_store().status(document_id)
        _record(operation, started, "available", document_id=document_id, count=payload["counts"].get("edges", 0))
        return payload
    except GraphNotIndexed:
        _record(operation, started, "not_indexed", document_id=document_id)
        return {"status": "not_indexed", "document_id": document_id}
    except GraphUnavailable as exc:
        logger.exception("reference_graph unavailable document_id=%s", document_id)
        _record(operation, started, "graph_unavailable", document_id=document_id, error=type(exc).__name__)
        return {"status": "graph_unavailable", "document_id": document_id}
    except Exception as exc:  # fail closed: a graph problem can never affect chat or health.
        logger.exception("reference_graph unexpected failure document_id=%s", document_id)
        _record(operation, started, "graph_unavailable", document_id=document_id, error=type(exc).__name__)
        return {"status": "graph_unavailable", "document_id": document_id}


@router.get("/status")
def reference_graph_status(document_id: str = Query(default=GRAPH_DOCUMENT_ID, min_length=1, max_length=160)):
    return _availability(document_id, "status")


@router.get("/neighborhood")
def reference_graph_neighborhood(
    document_id: str = Query(min_length=1, max_length=160),
    focus_provision_id: str = Query(min_length=1, max_length=500),
):
    availability = _availability(document_id, "neighborhood")
    if availability["status"] != "available":
        return availability
    started = perf_counter()
    try:
        payload = graph_store().neighborhood(document_id, focus_provision_id)
        _record("neighborhood_lookup", started, payload["status"], document_id=document_id, focus=focus_provision_id,
                count=len(payload.get("edges", [])))
        return payload
    except GraphNotIndexed:
        _record("neighborhood_lookup", started, "not_indexed", document_id=document_id)
        return {"status": "not_indexed", "document_id": document_id}
    except GraphUnavailable as exc:
        logger.exception("reference_graph neighborhood unavailable document_id=%s", document_id)
        _record("neighborhood_lookup", started, "graph_unavailable", document_id=document_id, error=type(exc).__name__)
        return {"status": "graph_unavailable", "document_id": document_id}
    except Exception as exc:
        logger.exception("reference_graph neighborhood failure document_id=%s", document_id)
        _record("neighborhood_lookup", started, "graph_unavailable", document_id=document_id, error=type(exc).__name__)
        return {"status": "graph_unavailable", "document_id": document_id}
