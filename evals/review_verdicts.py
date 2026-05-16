"""Print judge verdicts from results.json for manual review.

Usage:
    python -m evals.review_verdicts                      # all cases
    python -m evals.review_verdicts --fails-only         # only FAIL / L1_FAIL
    python -m evals.review_verdicts --file path/to.json  # custom results file
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_RESULTS_PATH = ROOT / "results.json"

PASS_MARK = "PASS    "
FAIL_MARK = "FAIL    "
L1_MARK   = "L1_FAIL "
SKIP_MARK = "SKIP    "


def _verdict(result: dict) -> tuple[str, str]:
    """Return (mark, reason) for a single result record."""
    if l1 := result.get("l1_failures"):
        reasons = "; ".join(f"{k}: {v}" for k, v in l1.items())
        return L1_MARK, reasons

    judge = result.get("judge")
    if judge is None:
        return SKIP_MARK, "no judge output"

    # New schema: passed + critique
    if "passed" in judge:
        mark = PASS_MARK if judge["passed"] else FAIL_MARK
        return mark, judge.get("critique", "")

    # Old schema: citation_accuracy + policy_compliance + *_reason fields
    passed = judge.get("citation_accuracy", True) and judge.get("policy_compliance", True)
    reasons = []
    if not judge.get("citation_accuracy", True):
        reasons.append(judge.get("citation_reason", "citation failed"))
    if not judge.get("policy_compliance", True):
        reasons.append(judge.get("policy_reason", "policy failed"))
    reason = " | ".join(reasons) if reasons else (
        judge.get("citation_reason", "") or judge.get("policy_reason", "")
    )
    return (PASS_MARK if passed else FAIL_MARK), reason


def _print_summary(data: dict) -> None:
    summary = data.get("summary", {})
    print(f"Generated : {data.get('generated_at', 'unknown')}")
    print(f"Mode      : {summary.get('mode', 'unknown')}")
    print(f"Cases     : {summary.get('total_cases', '?')}")

    if "judge_pass_rate" in summary:
        rate = summary["judge_pass_rate"]
        passed = summary.get("judge_passed", "?")
        total = summary.get("judge_total", "?")
        print(f"Judge     : {passed}/{total} = {rate:.1%}")

    if l1 := summary.get("l1"):
        print("L1 assertions:")
        for name, stats in l1.items():
            print(f"  {name}: {stats['passed']}/{stats['total']} = {stats['rate']:.1%}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Review judge verdicts from an eval run.")
    parser.add_argument("--file", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--fails-only", action="store_true", help="Show only FAIL and L1_FAIL cases")
    args = parser.parse_args()

    data = json.loads(args.file.read_text(encoding="utf-8"))
    _print_summary(data)

    results = data.get("results", [])
    shown = 0

    for r in results:
        mark, reason = _verdict(r)

        if args.fails_only and mark in (PASS_MARK, SKIP_MARK):
            continue

        case = r["case"]
        print(f"[{mark}] {case['id']}")
        print(f"  Query   : {case['query']}")
        if case.get("expected_act_number"):
            print(f"  Expect  : Act {case['expected_act_number']} s{case.get('expected_section', '?')}")
        print(f"  Reason  : {reason[:400]}" if reason else "  Reason  : —")
        print()
        shown += 1

    if shown == 0:
        print("No cases to show.")


if __name__ == "__main__":
    main()
