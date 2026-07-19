"""Pure coverage, corpus-staleness, and subset helpers for the eval dashboard."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from agent.citation_keys import canonicalize_citation_key

THIN_COVERAGE_THRESHOLD = 5
BOUNDARY_COVERAGE_THRESHOLD = 0.20


def _normalized_pair(act_number: Any, section_number: Any) -> tuple[str, str] | None:
    if act_number is None or section_number is None:
        return None
    act, section = canonicalize_citation_key(act_number, section_number)
    return (act, section) if act and section else None


def required_section_pairs(cases: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return the distinct Act/section pairs required by citation-applicable cases."""
    pairs: set[tuple[str, str]] = set()
    for case in cases:
        if not case.get("citation_applicable"):
            continue
        pair = _normalized_pair(case.get("expected_act_number"), case.get("expected_section"))
        if pair:
            pairs.add(pair)
    return pairs


def missing_section_pairs(
    required_pairs: Iterable[tuple[Any, Any]],
    present_pairs: Iterable[tuple[Any, Any]],
) -> list[dict[str, str]]:
    """Return required pairs absent from the corpus, normalized and sorted."""
    required = {
        pair for act, section in required_pairs
        if (pair := _normalized_pair(act, section)) is not None
    }
    present = {
        pair for act, section in present_pairs
        if (pair := _normalized_pair(act, section)) is not None
    }
    return [
        {"act_number": act, "section_number": section}
        for act, section in sorted(required - present)
    ]


def coverage_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate dataset coverage and apply the dashboard's fixed advisory rules."""
    by_policy = Counter(str(case.get("expected_policy", "allow")) for case in cases)
    by_category = Counter(str(case.get("category", "unknown")) for case in cases)
    by_scenario = Counter(str(case.get("scenario", "unknown")) for case in cases)
    smoke_by_scenario = Counter(
        str(case.get("scenario", "unknown")) for case in cases if case.get("smoke")
    )

    flags: list[dict[str, Any]] = []
    for scenario, count in by_scenario.items():
        if count < THIN_COVERAGE_THRESHOLD:
            flags.append({
                "rule": "thin_scenario",
                "scenario": scenario,
                "count": count,
                "threshold": THIN_COVERAGE_THRESHOLD,
            })
    for category, count in by_category.items():
        if count < THIN_COVERAGE_THRESHOLD:
            flags.append({
                "rule": "thin_scenario",
                "category": category,
                "count": count,
                "threshold": THIN_COVERAGE_THRESHOLD,
            })
    block_pct = 0.0 if not cases else by_policy.get("block", 0) / len(cases)
    if block_pct < BOUNDARY_COVERAGE_THRESHOLD:
        flags.append({
            "rule": "weak_boundary_coverage",
            "block_pct": block_pct,
            "threshold": BOUNDARY_COVERAGE_THRESHOLD,
        })

    for scenario in by_scenario:
        if smoke_by_scenario.get(scenario, 0) == 0:
            flags.append({"rule": "no_smoke_coverage", "scenario": scenario})

    return {
        "total_cases": len(cases),
        "smoke_cases": sum(bool(case.get("smoke")) for case in cases),
        "by_policy": dict(by_policy),
        "by_category": dict(by_category),
        "by_scenario": dict(by_scenario),
        "gap_flags": flags,
    }


def select_cases(
    cases: list[dict[str, Any]],
    subset: str | dict[str, str],
) -> list[dict[str, Any]]:
    """Resolve the dashboard subset contract against a dataset."""
    if subset == "all":
        selected = list(cases)
    elif subset == "smoke":
        selected = [case for case in cases if case.get("smoke")]
    elif isinstance(subset, dict) and len(subset) == 1:
        key, value = next(iter(subset.items()))
        field = {"category": "category", "scenario": "scenario", "case_id": "id"}.get(key)
        if field is None or not isinstance(value, str) or not value:
            raise ValueError("Invalid eval subset")
        selected = [case for case in cases if case.get(field) == value]
    else:
        raise ValueError("Invalid eval subset")

    if not selected:
        raise ValueError("Eval subset matched no cases")
    return selected


def aggregate_scenarios(case_results: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Summarize end-to-end pass rates by scenario for a single run."""
    counts: dict[str, dict[str, int]] = {}
    for result in case_results:
        scenario = str(result.get("scenario", "unknown"))
        stats = counts.setdefault(scenario, {"passed": 0, "total": 0})
        stats["total"] += 1
        judge = result.get("judge")
        passed = not result.get("l1_failures") and isinstance(judge, dict) and judge.get("passed") is True
        stats["passed"] += int(passed)

    return {
        scenario: {
            "passed": stats["passed"],
            "total": stats["total"],
            "rate": stats["passed"] / stats["total"],
        }
        for scenario, stats in counts.items()
    }
