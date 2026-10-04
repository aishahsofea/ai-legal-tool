"""Run summary for the grounding set. Kept apart from the runner so the API can import it without building the judge."""
from __future__ import annotations

from collections import Counter
from typing import Any


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [result for result in results if "error" not in result]
    return {
        "total_cases": len(results),
        "judge_errors": len(results) - len(judged),
        "matched": sum(result["match"] for result in judged),
        "match_rate": sum(result["match"] for result in judged) / len(judged) if judged else 0.0,
        "by_error_kind": dict(Counter(result["error_kind"] for result in judged if result["error_kind"])),
        "jev_cleared": sum(result["jev_cleared"] for result in results),
        "jev_errors": sum(result["jev_error"] for result in results),
    }
