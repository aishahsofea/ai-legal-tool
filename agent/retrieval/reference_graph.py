"""Bounded, provenance-safe adapter from retrieval chunks to promoted graph edges."""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Literal, TypedDict

from agent.feature_flags import flag_enabled
from agent.retrieval.search import (
    exact_section_lookup,
    exact_section_lookup_for_document,
    extract_act_hint,
    extract_section_number,
    get_connection,
)
from reference_graph.models import RELATIONSHIP_KINDS
from reference_graph.store import (
    GraphNotIndexed,
    ReferenceGraphStore,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MAX_REFERENCE_EDGES = 5
_PROVISION_SECTION_RE = re.compile(r"(?:^|/)section:([^/]+)", re.IGNORECASE)
_PROVISION_ACT_RE = re.compile(r"^act:([^/]+)", re.IGNORECASE)

Direction = Literal["outgoing", "incoming", "both"]
Lookup = Callable[..., list[dict]]


@dataclass
class FollowOnceGuard:
    """Invocation-scoped concurrency guard for parallel model tool calls."""

    _claimed: bool = False
    _lock: Lock = field(default_factory=Lock)

    def claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True


class RetrievalReferenceContext(TypedDict):
    follow_allowed: bool
    follow_guard: FollowOnceGuard


def follow_references_enabled() -> bool:
    """The internal retrieval flag is independent of public graph UI/API flags."""
    return flag_enabled("FOLLOW_REFERENCES_ENABLED")


_REFERENCE_INTENT_PATTERNS = (
    re.compile(r"\brefer(?:s|red|enced|ring)?\s+(?:to|by)\b", re.IGNORECASE),
    re.compile(r"\bprovisions?\s+(?:referenced|cited|mentioned)\b", re.IGNORECASE),
    re.compile(r"\bsubject\s+to\b", re.IGNORECASE),
    re.compile(r"\bnotwithstanding\b", re.IGNORECASE),
    re.compile(
        r"\bdefin(?:ition|ed)\b.{0,80}\b(?:under|in|by)\s+(?:another\s+)?"
        r"(?:provision|section)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmerujuk\s+(?:kepada|oleh)\b", re.IGNORECASE),
    re.compile(r"\btertakluk\s+kepada\b", re.IGNORECASE),
    re.compile(r"\bwalau\s+apa\s+pun\b", re.IGNORECASE),
)
_TARGETED_FEEDBACK_RE = re.compile(
    r"\b(?:missing|missed|unsupported)\b.{0,100}\b"
    r"(?:directly\s+)?refer(?:red|enced|ence)\b",
    re.IGNORECASE,
)


def should_follow_references(query: str, feedback: str = "") -> bool:
    """Deterministic safety gate for explicit reference-traversal intent."""
    if any(pattern.search(str(query or "")) for pattern in _REFERENCE_INTENT_PATTERNS):
        return True
    return bool(_TARGETED_FEEDBACK_RE.search(str(feedback or "")))


@lru_cache(maxsize=8)
def _cached_store(root: str) -> ReferenceGraphStore:
    return ReferenceGraphStore(Path(root))


def reference_graph_store() -> ReferenceGraphStore:
    root = os.getenv("REFERENCE_GRAPH_ROOT", str(ROOT / "data" / "reference_graph"))
    return _cached_store(root)


def empty_reference_metrics(*, disabled: bool = False) -> dict[str, int]:
    return {
        "calls": 0,
        "skipped": 0,
        "disabled": int(disabled),
        "unavailable": 0,
        "edges_considered": 0,
        "edges_returned": 0,
        "targets_looked_up": 0,
        "targets_resolved": 0,
        "targets_failed": 0,
        "boundary_targets": 0,
        "fail_open": 0,
    }


def _result(
    status: str,
    reason: str,
    *,
    metrics: dict[str, int],
    chunks: list[dict] | None = None,
    **details: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "chunks": chunks or [],
        "metrics": metrics,
        **details,
    }


def _normalise_act(act: str) -> str | None:
    value = str(act or "").strip()
    if not value or len(value) > 160:
        return None
    if re.fullmatch(r"\d+[A-Z]?", value, re.IGNORECASE):
        return value.upper()
    act_number, _act_title = extract_act_hint(value)
    return act_number


def _normalise_focus(act_number: str, provision: str) -> str | None:
    value = str(provision or "").strip()
    if not value or len(value) > 160:
        return None
    if value.casefold().startswith("act:"):
        provision_act = _act_number(value)
        return value if provision_act == act_number else None
    section = extract_section_number(value)
    if not section:
        match = re.fullmatch(r"(?:section\s*)?(\d+[A-Z]{0,2})", value, re.IGNORECASE)
        section = match.group(1).upper() if match else None
    return f"act:{act_number}/section:{section}" if section else None


def _act_number(provision_id: str) -> str | None:
    match = _PROVISION_ACT_RE.search(str(provision_id))
    return match.group(1).upper() if match else None


def _section_number(provision_id: str) -> str | None:
    match = _PROVISION_SECTION_RE.search(str(provision_id))
    return match.group(1).upper() if match else None


def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    evidence = edge.get("evidence") if isinstance(edge.get("evidence"), dict) else {}
    try:
        start_offset = int(evidence.get("start_offset", -1))
    except (TypeError, ValueError):
        start_offset = -1
    return (
        str(edge.get("source_provision_id", "")),
        str(edge.get("target_provision_id", "")),
        str(edge.get("relationship", "")),
        str(edge.get("reference_kind", "")),
        start_offset,
        str(edge.get("edge_id", "")),
    )


def _anchor_identity(
    retrieved_chunks: list[dict],
    *,
    act_number: str,
    section_number: str,
    requested_document_id: str | None,
) -> tuple[str, str] | None:
    matches = [
        chunk
        for chunk in retrieved_chunks
        if str(chunk.get("act_number", "")).upper() == act_number
        and str(chunk.get("section_number", "")).upper() == section_number
        and chunk.get("document_id")
        and chunk.get("extraction_id")
        and (
            not requested_document_id
            or str(chunk.get("document_id")) == requested_document_id
        )
    ]
    identities = {
        (str(chunk["document_id"]), str(chunk["extraction_id"]))
        for chunk in matches
    }
    return next(iter(identities)) if len(identities) == 1 else None


def _evidence_pages(edge: dict[str, Any]) -> list[int]:
    evidence = edge.get("evidence") if isinstance(edge.get("evidence"), dict) else {}
    pages = evidence.get("pages") if isinstance(evidence.get("pages"), list) else []
    return sorted({
        int(page["page_number"])
        for page in pages
        if isinstance(page, dict) and isinstance(page.get("page_number"), int)
    })


def _tag_chunk(
    chunk: dict,
    *,
    source_document_id: str,
    source_act: str,
    related_provision_id: str,
    cross_act: bool,
    directions: list[str],
) -> dict:
    tagged = dict(chunk)
    tagged["_reference_context"] = {
        "source_document_id": source_document_id,
        "source_act_number": source_act,
        "related_provision_id": related_provision_id,
        "directions": directions,
        "provenance_scope": (
            "version_neutral_cross_act_independent_corpus"
            if cross_act
            else "same_exact_document_and_extraction"
        ),
    }
    return tagged


def _compatible_target_rows(
    rows: list[dict],
    *,
    act_number: str,
    section_number: str,
    document_id: str | None = None,
    extraction_id: str | None = None,
) -> list[dict]:
    """Keep only rows whose exact corpus identity matches the requested target."""
    return [
        row
        for row in rows
        if str(row.get("act_number", "")).upper() == act_number
        and str(row.get("section_number", "")).upper() == section_number
        and row.get("document_id")
        and row.get("extraction_id")
        and (not document_id or str(row.get("document_id")) == document_id)
        and (not extraction_id or str(row.get("extraction_id")) == extraction_id)
    ]


def _unique_identity_row(rows: list[dict]) -> dict | None:
    """Fail closed when candidate rows span more than one corpus identity.

    Several rows sharing one (document_id, extraction_id) are just the section's
    own chunks; rows spanning different identities mean the lookup couldn't tell
    which corpus version is the real target, so no row should be picked.
    """
    identities = {
        (str(row.get("document_id")), str(row.get("extraction_id")))
        for row in rows
    }
    return rows[0] if len(identities) == 1 else None


def follow_published_references(
    *,
    act: str,
    provision: str,
    retrieved_chunks: list[dict],
    direction: Direction = "outgoing",
    relationship_kinds: list[str] | None = None,
    max_edges: int = MAX_REFERENCE_EDGES,
    document_id: str | None = None,
    store: ReferenceGraphStore | None = None,
    same_act_lookup: Lookup = exact_section_lookup_for_document,
    cross_act_lookup: Lookup = exact_section_lookup,
) -> dict[str, Any]:
    """Resolve one exact anchor and retrieve direct published reference targets.

    Graph records identify targets but never become answer/citation chunks.
    Same-Act target text must come from the anchor's exact document/extraction;
    cross-Act target text, when independently available, keeps its own verified
    corpus identity and remains explicitly version-neutral relative to the source.
    """
    metrics = empty_reference_metrics()
    metrics["calls"] = 1
    if direction not in {"outgoing", "incoming", "both"}:
        metrics["skipped"] = 1
        return _result("skipped", "invalid_direction", metrics=metrics)

    act_number = _normalise_act(act)
    focus_id = _normalise_focus(act_number or "", provision) if act_number else None
    focus_section = _section_number(focus_id or "")
    if not act_number or not focus_id or not focus_section:
        metrics["skipped"] = 1
        return _result("skipped", "invalid_anchor", metrics=metrics)

    requested_filters = relationship_kinds or []
    if len(requested_filters) > 8 or any(
        len(str(kind)) > 64 for kind in requested_filters
    ):
        metrics["skipped"] = 1
        return _result(
            "skipped",
            "invalid_relationship_kind",
            metrics=metrics,
            allowed_relationship_kinds=sorted(RELATIONSHIP_KINDS),
        )
    filters = {
        str(kind).strip()
        for kind in requested_filters
        if str(kind).strip()
    }
    if not filters.issubset(RELATIONSHIP_KINDS):
        metrics["skipped"] = 1
        return _result(
            "skipped",
            "invalid_relationship_kind",
            metrics=metrics,
            allowed_relationship_kinds=sorted(RELATIONSHIP_KINDS),
        )

    identity = _anchor_identity(
        retrieved_chunks,
        act_number=act_number,
        section_number=focus_section,
        requested_document_id=document_id,
    )
    if identity is None:
        metrics["skipped"] = 1
        return _result(
            "skipped",
            "exact_anchor_identity_unavailable",
            metrics=metrics,
            focus_provision_id=focus_id,
        )
    anchor_document_id, anchor_extraction_id = identity

    graph_store = store or reference_graph_store()
    try:
        graph_document = graph_store.document(anchor_document_id)
        if (
            str(graph_document.get("corpus_document_id", "")) != anchor_document_id
            or str(graph_document.get("act_number", "")).upper() != act_number
        ):
            metrics["skipped"] = 1
            metrics["fail_open"] = 1
            return _result(
                "skipped",
                "graph_snapshot_corpus_mismatch",
                metrics=metrics,
                focus_provision_id=focus_id,
            )
        neighborhood = graph_store.published_edges(
            anchor_document_id,
            focus_id,
            direction=direction,
            include_descendants=True,
        )
    except GraphNotIndexed:
        metrics["unavailable"] = 1
        metrics["fail_open"] = 1
        return _result(
            "graph_unavailable",
            "not_indexed",
            metrics=metrics,
            focus_provision_id=focus_id,
        )
    except Exception:
        logger.warning(
            "follow_references graph unavailable",
            extra={"document_id": anchor_document_id, "focus_provision_id": focus_id},
            exc_info=True,
        )
        metrics["unavailable"] = 1
        metrics["fail_open"] = 1
        return _result(
            "graph_unavailable",
            "malformed_or_unavailable",
            metrics=metrics,
            focus_provision_id=focus_id,
        )

    if neighborhood.get("status") != "available":
        metrics["skipped"] = 1
        metrics["fail_open"] = 1
        return _result(
            "skipped",
            "anchor_not_in_graph",
            metrics=metrics,
            focus_provision_id=focus_id,
        )

    edges = sorted(neighborhood.get("edges", []), key=_edge_key)
    if filters:
        edges = [edge for edge in edges if edge.get("relationship") in filters]
    metrics["edges_considered"] = len(edges)
    try:
        edge_limit = max(0, min(int(max_edges), MAX_REFERENCE_EDGES))
    except (TypeError, ValueError):
        edge_limit = MAX_REFERENCE_EDGES
    selected = edges[:edge_limit]
    metrics["edges_returned"] = len(selected)

    local_nodes = {
        str(node.get("provision_id"))
        for node in neighborhood.get("nodes", [])
        if isinstance(node, dict) and node.get("provision_id")
    }
    edge_results: list[dict[str, Any]] = []
    targets: dict[str, dict[str, Any]] = {}
    for edge in selected:
        source_id = str(edge["source_provision_id"])
        target_id = str(edge["target_provision_id"])
        source_in_scope = source_id == focus_id or source_id.startswith(f"{focus_id}/")
        if direction == "incoming":
            edge_direction = "incoming"
            related_id = source_id
        elif direction == "outgoing":
            edge_direction = "outgoing"
            related_id = target_id
        elif source_in_scope:
            edge_direction = "outgoing"
            related_id = target_id
        else:
            edge_direction = "incoming"
            related_id = source_id
        boundary = related_id not in local_nodes
        item = {
            "edge_id": str(edge.get("edge_id", "")),
            "direction": edge_direction,
            "source_provision_id": source_id,
            "target_provision_id": target_id,
            "related_provision_id": related_id,
            "relationship": str(edge.get("relationship", "")),
            "reference_kind": str(edge.get("reference_kind", "")),
            "evidence_pages": _evidence_pages(edge),
            "boundary": boundary,
        }
        edge_results.append(item)
        targets.setdefault(related_id, {"boundary": boundary, "edges": []})["edges"].append(item)

    followed_chunks: list[dict] = []
    target_results: list[dict[str, Any]] = []
    uses_default_lookups = (
        same_act_lookup is exact_section_lookup_for_document
        and cross_act_lookup is exact_section_lookup
    )
    lookup_conn = get_connection() if targets and uses_default_lookups else None
    try:
        for related_id in sorted(targets):
            target = targets[related_id]
            related_act = _act_number(related_id)
            related_section = _section_number(related_id)
            boundary = bool(target["boundary"])
            metrics["boundary_targets"] += int(boundary)
            target_result = {
                "provision_id": related_id,
                "boundary": boundary,
                "lookup_status": "not_attempted",
            }
            if not related_act or not related_section:
                metrics["targets_failed"] += 1
                metrics["fail_open"] = 1
                target_result["lookup_status"] = "unsupported_provision_kind"
                target_results.append(target_result)
                continue

            metrics["targets_looked_up"] += 1
            try:
                if related_act == act_number:
                    rows = same_act_lookup(
                        related_section,
                        act_number=related_act,
                        document_id=anchor_document_id,
                        extraction_id=anchor_extraction_id,
                        conn=lookup_conn,
                    )
                    rows = _compatible_target_rows(
                        rows,
                        act_number=related_act,
                        section_number=related_section,
                        document_id=anchor_document_id,
                        extraction_id=anchor_extraction_id,
                    )
                    cross_act = False
                else:
                    rows = cross_act_lookup(
                        related_section, act_number=related_act, conn=lookup_conn
                    )
                    rows = _compatible_target_rows(
                        rows,
                        act_number=related_act,
                        section_number=related_section,
                    )
                    cross_act = True
            except Exception:
                logger.warning(
                    "follow_references target lookup failed",
                    extra={
                        "source_document_id": anchor_document_id,
                        "related_provision_id": related_id,
                    },
                    exc_info=True,
                )
                rows = []
                cross_act = related_act != act_number

            if not rows:
                metrics["targets_failed"] += 1
                metrics["fail_open"] = 1
                target_result["lookup_status"] = "not_found_in_compatible_corpus"
                target_results.append(target_result)
                continue

            resolved_row = _unique_identity_row(rows)
            if resolved_row is None:
                metrics["targets_failed"] += 1
                metrics["fail_open"] = 1
                target_result["lookup_status"] = "ambiguous_corpus_identity"
                target_results.append(target_result)
                continue

            resolved = _tag_chunk(
                resolved_row,
                source_document_id=anchor_document_id,
                source_act=act_number,
                related_provision_id=related_id,
                cross_act=cross_act,
                directions=sorted({
                    str(edge["direction"])
                    for edge in target["edges"]
                }),
            )
            followed_chunks.append(resolved)
            metrics["targets_resolved"] += 1
            target_result.update({
                "lookup_status": "resolved",
                "document_id": str(resolved["document_id"]),
                "extraction_id": str(resolved["extraction_id"]),
                "provenance_scope": resolved["_reference_context"]["provenance_scope"],
            })
            target_results.append(target_result)
    finally:
        if lookup_conn is not None:
            lookup_conn.close()

    reason = "followed" if selected else "no_published_edges"
    return _result(
        "followed",
        reason,
        metrics=metrics,
        chunks=followed_chunks,
        source_document_id=anchor_document_id,
        source_extraction_id=anchor_extraction_id,
        focus_provision_id=focus_id,
        direction=direction,
        edges=edge_results,
        targets=target_results,
    )
