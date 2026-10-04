"""Jev first pass on evals/grounding_dataset.json (#201); live API, needs TYPESAFE_API_KEY and JEV_MODEL."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from agent.jev_client import JevError, supported_probability
from evals.grounding_inputs import draft, source

GROUNDING_PATH = Path(__file__).resolve().parent / "grounding_dataset.json"
THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.97, 0.99)


def score_case(case: dict) -> dict:
    row = {"id": case["id"], "verdict": case["verdict"], "language": case["language"]}
    try:
        row["score"] = supported_probability(draft(case), [source(case)])
    except JevError as exc:
        row["error"] = str(exc)[:300]
    return row


def report(rows: list[dict]) -> str:
    scored = [row for row in rows if "score" in row]
    errors = [row for row in rows if "error" in row]
    lines = [
        f"cases: {len(rows)}  scored: {len(scored)}  jev errors: {len(errors)}",
        f"verdicts: {dict(Counter(r['verdict'] for r in scored))}",
        "",
        "| threshold | unsupported cleared | partial cleared | supported cleared | share reaching Ultra |",
        "|---|---|---|---|---|",
    ]
    for threshold in THRESHOLDS:
        by_verdict = {v: [r for r in scored if r["verdict"] == v] for v in ("unsupported", "partial", "supported")}
        cleared = {v: sum(r["score"] >= threshold for r in rs) for v, rs in by_verdict.items()}
        reaching = sum(r["score"] < threshold for r in scored) / max(len(scored), 1)
        lines.append(
            f"| {threshold} | {cleared['unsupported']}/{len(by_verdict['unsupported'])} "
            f"| {cleared['partial']}/{len(by_verdict['partial'])} "
            f"| {cleared['supported']}/{len(by_verdict['supported'])} | {reaching:.1%} |"
        )
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
