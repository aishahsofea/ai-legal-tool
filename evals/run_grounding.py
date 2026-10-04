"""Run the real grounding judge over evals/grounding_dataset.json, one claim per line.

Live API: needs the GROUNDING_* judge credentials, plus TYPESAFE_API_KEY and JEV_MODEL
when the Jev first pass is on. No database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.jev_client import JevError, supported_probability
from agent.nodes.grounding_check import _jev_enabled, _jev_threshold, judge_claims
from evals.grounding_inputs import draft, source
from evals.grounding_summary import summarise

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "grounding_dataset.json"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "grounding.json"

# Strictness order: a judge label above the dataset verdict is too lenient, below it too strict.
_RANK = {"unsupported": 0, "partial": 1, "supported": 2}


def error_kind(verdict: str, judge_label: str) -> str | None:
    if verdict == judge_label:
        return None
    return "too_lenient" if _RANK[judge_label] > _RANK[verdict] else "too_strict"


def judge_case(case: dict[str, Any]) -> dict[str, Any]:
    """Mirror production: Jev gate first, then the judge. A Jev error falls through to the judge."""
    result: dict[str, Any] = {
        "id": case["id"],
        "case": case,
        "label": case["verdict"],
        "judge_label": None,
        "match": False,
        "error_kind": None,
        "jev_score": None,
        "jev_cleared": False,
        "jev_error": False,
        "claims_found": None,
        "reason": "",
        "quote": "",
    }
    answer, sources = draft(case), [source(case)]

    if _jev_enabled():
        try:
            result["jev_score"] = supported_probability(answer, sources)
            result["jev_cleared"] = result["jev_score"] >= _jev_threshold()
        except JevError:
            result["jev_error"] = True
        if result["jev_cleared"]:
            # Production treats a cleared answer as supported without calling the judge.
            result["judge_label"] = "supported"
            result["reason"] = "Jev cleared, judge skipped"
            return _finish(result)

    try:
        claims = judge_claims(answer, sources).claims
    except Exception as exc:
        # Production fails open here. An eval has to show the failure instead of a pass.
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result

    result["claims_found"] = len(claims)
    if not claims:
        # No extracted claim means no violation in production.
        result["judge_label"] = "supported"
        result["reason"] = "Judge extracted no claim"
        return _finish(result)
    # The draft holds one claim, but the judge may split it. The weakest label decides.
    worst = min(claims, key=lambda claim: _RANK[claim.support])
    result.update(judge_label=worst.support, reason=worst.reason, quote=worst.quote)
    return _finish(result)


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    result["match"] = result["label"] == result["judge_label"]
    result["error_kind"] = error_kind(result["label"], result["judge_label"])
    return result


def select_grounding_cases(
    cases: list[dict[str, Any]],
    *,
    case_ids: str | None = None,
    verdict: str | None = None,
    language: str | None = None,
    judgement_call: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        wanted = [part.strip() for part in case_ids.split(",") if part.strip()]
        unknown = sorted(set(wanted) - {case["id"] for case in cases})
        if unknown:
            raise ValueError(f"Unknown case ids: {', '.join(unknown)}")
        selected = [case for case in selected if case["id"] in set(wanted)]
    if verdict:
        wanted_verdicts = {part.strip() for part in verdict.split(",")}
        selected = [case for case in selected if case["verdict"] in wanted_verdicts]
    if language:
        wanted_languages = {part.strip() for part in language.split(",")}
        selected = [case for case in selected if case["language"] in wanted_languages]
    if judgement_call:
        selected = [case for case in selected if case.get("judgement_call")]
    if limit:
        selected = selected[:limit]
    if not selected:
        raise ValueError("Grounding subset matched no cases")
    return selected


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the grounding judge over the grounding dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--case-id", help="One case id; the dashboard's single-case subset.")
    parser.add_argument("--case-ids", help="Comma-separated case ids, e.g. g001,g002.")
    parser.add_argument("--verdict", help="Comma-separated dataset verdicts, e.g. partial,unsupported.")
    parser.add_argument("--language", help="Comma-separated claim languages, e.g. bm,mixed.")
    parser.add_argument("--judgement-call", action="store_true", help="Only cases flagged judgement_call.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jsonl", action="store_true", help="Emit one JSON object per completed claim")
    args = parser.parse_args()

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))["cases"]
    try:
        selected = select_grounding_cases(
            cases,
            case_ids=args.case_ids or args.case_id,
            verdict=args.verdict,
            language=args.language,
            judgement_call=args.judgement_call,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))

    results = []
    for case in selected:
        result = judge_case(case)
        results.append(result)
        if args.jsonl:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        else:
            shown = result["judge_label"] or f"ERROR {result.get('error', '')}"
            print(f"{case['id']}: dataset {result['label']}, judge {shown}"
                  f"{'' if result['match'] else ' MISMATCH'}", flush=True)

    summary = summarise(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not args.jsonl:
        print(f"\nMatched {summary['matched']}/{summary['total_cases']} = {summary['match_rate']:.1%}")
        print(f"Mismatches: {summary['by_error_kind']}  judge errors: {summary['judge_errors']}")
        print(f"Results written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
