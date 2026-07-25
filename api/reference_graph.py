"""Flag-gated, read-only statutory reference-graph endpoints."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from corpus.registry import DEFAULT_MANIFEST_PATH
from reference_graph.models import DEFAULT_GRAPH_DOCUMENT_ID
from reference_graph.store import (
    GraphNotIndexed,
    GraphPairMismatch,
    GraphUnavailable,
    ReferenceGraphStore,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix="/reference-graph", tags=["reference-graph"])
DOCUMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


def reference_graph_enabled() -> bool:
    """The only source of truth for graph exposure; default safely disabled."""
    return os.getenv("REFERENCE_GRAPH_ENABLED", "").strip().casefold() in {"1", "true", "yes", "on"}


def reference_graph_comparison_enabled() -> bool:
    """Comparison fails independently and is always off unless both flags are on."""
    return (
        reference_graph_enabled()
        and os.getenv("REFERENCE_GRAPH_COMPARISON_ENABLED", "").strip().casefold()
        in {"1", "true", "yes", "on"}
    )


def graph_store() -> ReferenceGraphStore:
    return ReferenceGraphStore(
        Path(os.getenv("REFERENCE_GRAPH_ROOT", ROOT / "data" / "reference_graph")),
        manifest_path=Path(os.getenv("CORPUS_MANIFEST_PATH", DEFAULT_MANIFEST_PATH)),
    )


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
def reference_graph_status(
    document_id: str = Query(
        default=DEFAULT_GRAPH_DOCUMENT_ID,
        min_length=1,
        max_length=160,
        pattern=DOCUMENT_ID_PATTERN,
    ),
):
    return _availability(document_id, "status")


@router.get("/neighborhood")
def reference_graph_neighborhood(
    document_id: str = Query(min_length=1, max_length=160, pattern=DOCUMENT_ID_PATTERN),
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


@router.get("/snapshots")
def reference_graph_snapshots(
    act_number: str = Query(default="265", min_length=1, max_length=40),
    language: str = Query(default="en", min_length=2, max_length=16),
):
    started = perf_counter()
    if not reference_graph_enabled():
        _record("snapshots", started, "flag-off", act_number=act_number, language=language)
        return {"status": "flag-off", "snapshots": []}
    if not reference_graph_comparison_enabled():
        _record("snapshots", started, "comparison_disabled", act_number=act_number, language=language)
        return {"status": "comparison_disabled", "comparison_enabled": False, "snapshots": []}
    try:
        snapshots = graph_store().available_snapshots(act_number=act_number, language=language)
        _record("snapshots", started, "available", act_number=act_number, language=language, count=len(snapshots))
        return {
            "status": "available",
            "act_number": act_number,
            "language": language,
            "comparison_enabled": reference_graph_comparison_enabled(),
            "snapshots": snapshots,
        }
    except Exception as exc:
        logger.exception("reference_graph snapshot catalog unavailable")
        _record("snapshots", started, "graph_unavailable", error=type(exc).__name__)
        return {"status": "graph_unavailable", "snapshots": []}


def _comparison_unavailable(
    store: ReferenceGraphStore,
    *,
    base_document_id: str,
    compare_document_id: str,
) -> dict[str, Any] | None:
    try:
        store.status(base_document_id)
    except GraphNotIndexed:
        return {
            "status": "not_indexed_base",
            "base_document_id": base_document_id,
            "compare_document_id": compare_document_id,
        }
    try:
        store.status(compare_document_id)
    except GraphNotIndexed:
        return {
            "status": "not_indexed_compare",
            "base_document_id": base_document_id,
            "compare_document_id": compare_document_id,
        }
    return None


@router.get("/compare")
def reference_graph_compare(
    request: Request,
    base_document_id: str = Query(min_length=1, max_length=160, pattern=DOCUMENT_ID_PATTERN),
    compare_document_id: str = Query(min_length=1, max_length=160, pattern=DOCUMENT_ID_PATTERN),
    focus_provision_id: str = Query(min_length=1, max_length=500),
):
    started = perf_counter()
    allowed = {"base_document_id", "compare_document_id", "focus_provision_id"}
    if set(request.query_params) != allowed or any(
        len(request.query_params.getlist(name)) != 1 for name in allowed
    ):
        raise HTTPException(status_code=422, detail="comparison accepts exactly one bounded snapshot pair and one focus")
    if base_document_id == compare_document_id:
        raise HTTPException(status_code=422, detail="base and comparison documents must differ")
    if not reference_graph_comparison_enabled():
        _record(
            "compare", started, "comparison_disabled",
            base_document_id=base_document_id, compare_document_id=compare_document_id,
            focus=focus_provision_id,
        )
        return {
            "status": "comparison_disabled",
            "base_document_id": base_document_id,
            "compare_document_id": compare_document_id,
            "focus_provision_id": focus_provision_id,
        }
    store = graph_store()
    try:
        unavailable = _comparison_unavailable(
            store,
            base_document_id=base_document_id,
            compare_document_id=compare_document_id,
        )
        if unavailable is not None:
            _record(
                "compare", started, unavailable["status"],
                base_document_id=base_document_id, compare_document_id=compare_document_id,
                focus=focus_provision_id,
            )
            return unavailable
        base_document = store.document(base_document_id)
        compare_document = store.document(compare_document_id)
        if (
            base_document.get("act_number") != compare_document.get("act_number")
            or base_document.get("language") != compare_document.get("language")
        ):
            raise HTTPException(status_code=422, detail="snapshot pair must have the same Act and language")
        payload = store.compare(base_document_id, compare_document_id, focus_provision_id)
        counts = payload.get("counts", {})
        _record(
            "compare", started, payload["status"],
            base_document_id=base_document_id, compare_document_id=compare_document_id,
            focus=focus_provision_id,
            added=counts.get("added", 0), removed=counts.get("removed", 0),
            unchanged=counts.get("unchanged", 0),
        )
        return payload
    except HTTPException:
        raise
    except GraphNotIndexed:
        # A deployment race after the explicit availability checks fails closed.
        _record(
            "compare", started, "graph_unavailable",
            base_document_id=base_document_id, compare_document_id=compare_document_id,
            focus=focus_provision_id, error="GraphNotIndexed",
        )
        return {
            "status": "graph_unavailable",
            "base_document_id": base_document_id,
            "compare_document_id": compare_document_id,
        }
    except GraphPairMismatch as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "reference_graph comparison failure base_document_id=%s compare_document_id=%s focus=%s",
            base_document_id, compare_document_id, focus_provision_id,
        )
        _record(
            "compare", started, "graph_unavailable",
            base_document_id=base_document_id, compare_document_id=compare_document_id,
            focus=focus_provision_id, error=type(exc).__name__,
        )
        return {
            "status": "graph_unavailable",
            "base_document_id": base_document_id,
            "compare_document_id": compare_document_id,
        }
