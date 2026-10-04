"""Jev first pass on evals/grounding_dataset.json (#201); live API, needs TYPESAFE_API_KEY and JEV_MODEL."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from agent.jev_client import JevError, supported_probability
from agent.nodes.claim_splitter import split_claims

GROUNDING_PATH = Path(__file__).resolve().parent / "grounding_dataset.json"
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)


def _draft(case: dict) -> str:
    return f"Here is the position.\n\n{case['claim']}\n\nThis is not legal advice."


def _source(case: dict) -> str:
    return (
        f"({case['act_title']}, Act {case['act_number']}, Section {case['section_number']}):\n"
        f"{case['source_text']}"
    )


def score_case(case: dict) -> dict:
    claims = split_claims(_draft(case))
    row = {"id": case["id"], "verdict": case["verdict"], "language": case["language"],
           "claims": len(claims), "split_ok": claims == [case["claim"]]}
    try:
        row["scores"] = [supported_probability(claim, _source(case)) for claim in claims]
    except JevError as exc:
        row["error"] = str(exc)[:300]
    return row


def _clears(row: dict, threshold: float) -> bool:
    # No claims extracted means nothing for Jev to check, so it must not clear.
    return bool(row["scores"]) and all(score >= threshold for score in row["scores"])


def report(rows: list[dict]) -> str:
    scored = [row for row in rows if "scores" in row]
    errors = [row for row in rows if "error" in row]
    lines = [
        f"cases: {len(rows)}  scored: {len(scored)}  jev errors: {len(errors)}",
        f"splitter returned exactly the labelled claim: {sum(r['split_ok'] for r in rows)}/{len(rows)}",
        f"verdicts: {dict(Counter(r['verdict'] for r in scored))}",
        "",
        "| threshold | unsupported cleared | partial cleared | supported cleared | share reaching Ultra |",
        "|---|---|---|---|---|",
    ]
    for threshold in THRESHOLDS:
        by_verdict = {v: [r for r in scored if r["verdict"] == v] for v in ("unsupported", "partial", "supported")}
        cleared = {v: sum(_clears(r, threshold) for r in rs) for v, rs in by_verdict.items()}
        reaching = sum(not _clears(r, threshold) for r in scored) / max(len(scored), 1)
        lines.append(
            f"| {threshold} | {cleared['unsupported']}/{len(by_verdict['unsupported'])} "
            f"| {cleared['partial']}/{len(by_verdict['partial'])} "
            f"| {cleared['supported']}/{len(by_verdict['supported'])} | {reaching:.1%} |"
        )
    missed = [r["id"] for r in rows if not r["split_ok"]]
    if missed:
        lines += ["", f"splitter misses: {missed}"]
    return "\n".join(lines)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="first N cases only, to iterate cheaply")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", type=Path, help="write per-case rows as JSON")
    args = parser.parse_args()

    cases = json.loads(GROUNDING_PATH.read_text())["cases"][: args.limit]
    with cf.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(score_case, cases))
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(report(rows))


if __name__ == "__main__":
    main()
