"""Pure one-hop comparison of independently audited snapshot neighborhoods."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from hashlib import sha256
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_reference_wording(value: object) -> str:
    """Normalize representation noise without inventing statutory meaning."""
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return _WHITESPACE_RE.sub(" ", normalized).strip().casefold()


def logical_reference_key(edge: dict[str, Any]) -> dict[str, str]:
    """Return the document-offset-independent identity of an observed reference."""
    evidence = edge.get("evidence", {})
    literal = evidence.get("text", "") if isinstance(evidence, dict) else ""
    return {
        "source_provision_id": str(edge.get("source_provision_id", "")),
        "target_provision_id": str(edge.get("target_provision_id", "")),
        "reference_kind": normalize_reference_wording(edge.get("reference_kind", "")),
        "relationship": normalize_reference_wording(edge.get("relationship", "")),
        "literal_wording": normalize_reference_wording(literal),
    }


def _key_tuple(edge: dict[str, Any]) -> tuple[str, str, str, str, str]:
    key = logical_reference_key(edge)
    return (
        key["source_provision_id"],
        key["target_provision_id"],
        key["reference_kind"],
        key["relationship"],
        key["literal_wording"],
    )


def _edge_order(edge: dict[str, Any]) -> tuple[int, int, int, str]:
    evidence = edge.get("evidence", {})
    pages = evidence.get("pages", []) if isinstance(evidence, dict) else []
    page = pages[0].get("page_number", 0) if pages and isinstance(pages[0], dict) else 0
    return (
        int(page or 0),
        int(evidence.get("start_offset", 0)) if isinstance(evidence, dict) else 0,
        int(evidence.get("end_offset", 0)) if isinstance(evidence, dict) else 0,
        str(edge.get("edge_id", "")),
    )


def _group(edges: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        result[_key_tuple(edge)].append(edge)
    for values in result.values():
        values.sort(key=_edge_order)
    return result


def _logical_id(key: dict[str, str], ordinal: int) -> str:
    payload = json.dumps(
        {"key": key, "occurrence_ordinal": ordinal},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"logical-reference:{sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _union_nodes(
    base_nodes: list[dict[str, Any]],
    compare_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = {str(node["provision_id"]): node for node in base_nodes}
    compare = {str(node["provision_id"]): node for node in compare_nodes}
    result = []
    for provision_id in sorted(set(base) | set(compare)):
        base_node = base.get(provision_id)
        compare_node = compare.get(provision_id)
        result.append({
            "provision_id": provision_id,
            "presence": (
                "both" if base_node is not None and compare_node is not None
                else "base" if base_node is not None
                else "compare"
            ),
            "base_node": base_node,
            "compare_node": compare_node,
        })
    return result


def compare_neighborhoods(
    base: dict[str, Any],
    compare: dict[str, Any],
    *,
    base_document_id: str,
    compare_document_id: str,
    focus_provision_id: str,
) -> dict[str, Any]:
    """Compare the multiset union; changed wording is naturally removed + added."""
    if base.get("status") != "available" or compare.get("status") != "available":
        raise ValueError("comparison_requires_available_neighborhoods")
    base_groups = _group(list(base.get("edges", [])))
    compare_groups = _group(list(compare.get("edges", [])))
    references = []
    counts = {"added": 0, "removed": 0, "unchanged": 0}
    for key_tuple in sorted(set(base_groups) | set(compare_groups)):
        base_edges = base_groups.get(key_tuple, [])
        compare_edges = compare_groups.get(key_tuple, [])
        width = max(len(base_edges), len(compare_edges))
        key = logical_reference_key((base_edges or compare_edges)[0])
        for index in range(width):
            base_edge = base_edges[index] if index < len(base_edges) else None
            compare_edge = compare_edges[index] if index < len(compare_edges) else None
            status = (
                "unchanged" if base_edge is not None and compare_edge is not None
                else "removed" if base_edge is not None
                else "added"
            )
            counts[status] += 1
            ordinal = index + 1
            references.append({
                "logical_reference_id": _logical_id(key, ordinal),
                "logical_key": key,
                "occurrence_ordinal": ordinal,
                "status": status,
                "base_edge": base_edge,
                "compare_edge": compare_edge,
            })
    return {
        "status": "available",
        "base_document_id": base_document_id,
        "compare_document_id": compare_document_id,
        "focus_provision_id": focus_provision_id,
        "focus_presence": {"base": True, "compare": True},
        "counts": counts,
        "nodes": _union_nodes(list(base.get("nodes", [])), list(compare.get("nodes", []))),
        "references": references,
    }
