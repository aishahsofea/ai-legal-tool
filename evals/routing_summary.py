"""Scoring for the router eval. No router import, so the API can import it without credentials."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

LEGAL_TYPES = frozenset({"statute_lookup", "topical", "provision_extraction"})


def miss_direction(label: str, got: str) -> str | None:
    if label == got:
        return None
    if label == "clarify" and got in LEGAL_TYPES:
        return "clarify_to_legal"
    if label in LEGAL_TYPES and got == "clarify":
        return "legal_to_clarify"
    if label in LEGAL_TYPES and got == "conversational":
        return "legal_to_conversational"
    return "other"


def _rate(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _group(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(entries),
        "type_accuracy": _rate(sum(e["type_match"] for e in entries), len(entries)),
        "language_accuracy": _rate(sum(e["language_match"] for e in entries), len(entries)),
    }


def _grouped(entries: list[dict[str, Any]], keys) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        for key in keys(entry):
            buckets[key].append(entry)
    return {key: _group(bucket) for key, bucket in sorted(buckets.items())}


def _agreement(scored: list[dict[str, Any]], repeats: int) -> dict[str, Any] | None:
    if repeats <= 1:
        return None
    by_case: dict[str, set[str]] = defaultdict(set)
    for entry in scored:
        by_case[entry["id"]].add(entry["query_type"])
    agree = sum(len(types) == 1 for types in by_case.values())
    return {"cases": len(by_case), "agree": agree, "rate": _rate(agree, len(by_case))}


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in results if "error" not in r]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for entry in scored:
        confusion[entry["label_type"]][entry["query_type"]] += 1
    directions = Counter(e["miss_direction"] for e in scored if e["miss_direction"])
    repeats = max((r["repeat"] for r in results), default=-1) + 1
    return {
        "total_cases": len({r["id"] for r in results}),
        "total_runs": len(results),
        "errors": len(results) - len(scored),
        "by_error": dict(Counter(r["error"] for r in results if "error" in r)),
        "query_type_accuracy": _rate(sum(e["type_match"] for e in scored), len(scored)),
        "language_accuracy": _rate(sum(e["language_match"] for e in scored), len(scored)),
        "confusion": {label: dict(row) for label, row in sorted(confusion.items())},
        "by_tag": _grouped(scored, lambda e: e.get("tags", [])),
        "by_language": _grouped(scored, lambda e: [e["label_language"]]),
        "by_query_type": _grouped(scored, lambda e: [e["label_type"]]),
        # A gate run must show zero `fallback` rows, or its numbers are the LLM router's.
        "by_path": {
            path: sum(e.get("route_path", "llm") == path for e in scored)
            for path in ("jev", "llm", "fallback")
        },
        "miss_directions": {
            key: directions.get(key, 0)
            for key in ("clarify_to_legal", "legal_to_clarify", "legal_to_conversational", "other")
        },
        "agreement": _agreement(scored, repeats),
    }
