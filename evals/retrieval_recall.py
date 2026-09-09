"""Retrieval recall@k for dataset cases that name one expected section.

Separates retrieval from answer quality. A judge failure can mean the retriever
never surfaced the right section, or that synthesis mangled a good chunk;
recall@k answers the first half on its own, and it is the number an embedding
or reranking change is compared against (issues #41, #42).

Runs no LLM: one embedding call per case, then a vector search. Cases with no
`expected_section` (escalation, out-of-corpus) are skipped — there is no
correct chunk to find.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.citation_keys import normalized_citation_pair
from agent.retrieval.search import (
    exact_section_lookup,
    extract_act_hint,
    extract_section_number,
    semantic_search,
)

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = ROOT / "dataset.json"
CUTOFFS = (1, 3, 8)
TOP_K = max(CUTOFFS)


def _rank_of_expected(rows: list[dict[str, Any]], expected: tuple[str, str]) -> int | None:
    """1-based rank of the expected section, or None if it is not in `rows`."""
    for position, row in enumerate(rows, 1):
        pair = normalized_citation_pair(row.get("act_number"), row.get("section_number"))
        if pair == expected:
            return position
    return None


def _retrieve(query: str, mode: str) -> list[dict[str, Any]]:
    if mode == "semantic":
        return semantic_search(query, top_k=TOP_K)
    # `retriever` mirrors retriever_node on a statute_lookup query: try the exact
    # section lookup first, fall back to vector search. It measures what the
    # agent actually sees; `semantic` measures the embedding on its own.
    section = extract_section_number(query)
    act_number, act_title = extract_act_hint(query)
    rows = exact_section_lookup(section, act_number, act_title) if section else []
    return rows or semantic_search(query, top_k=TOP_K)


def _summarize(ranks: list[int | None]) -> dict[str, Any]:
    total = len(ranks)
    summary: dict[str, Any] = {"cases": total}
    for k in CUTOFFS:
        hits = sum(1 for rank in ranks if rank is not None and rank <= k)
        summary[f"recall@{k}"] = hits / total if total else 0.0
    summary["misses"] = sum(1 for rank in ranks if rank is None)
    return summary


def measure(cases: list[dict[str, Any]], mode: str, *, progress: bool = True) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        expected = normalized_citation_pair(
            case.get("expected_act_number"), case.get("expected_section")
        )
        if expected is None:
            continue
        if progress:
            print(f"[{index}/{len(cases)}] {case['id']} ...", flush=True)
        rows = _retrieve(case["query"], mode)
        rank = _rank_of_expected(rows, expected)
        per_case.append({
            "id": case["id"],
            "language": case.get("language", "en"),
            "scenario": case.get("scenario"),
            "expected": {"act_number": expected[0], "section_number": expected[1]},
            "rank": rank,
            "retrieved": [
                {"act_number": row.get("act_number"), "section_number": row.get("section_number")}
                for row in rows[:TOP_K]
            ],
        })

    by_language: dict[str, list[int | None]] = defaultdict(list)
    for result in per_case:
        by_language[result["language"]].append(result["rank"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "summary": {
            "overall": _summarize([result["rank"] for result in per_case]),
            "by_language": {
                language: _summarize(ranks) for language, ranks in sorted(by_language.items())
            },
        },
        "results": per_case,
    }


def _print_report(report: dict[str, Any]) -> None:
    def line(label: str, stats: dict[str, Any]) -> str:
        cutoffs = "  ".join(f"@{k}: {stats[f'recall@{k}']:.0%}" for k in CUTOFFS)
        return f"  {label:<10} n={stats['cases']:<4} {cutoffs}   missed: {stats['misses']}"

    print(f"\nRetrieval recall ({report['mode']} mode)")
    print(line("overall", report["summary"]["overall"]))
    for language, stats in report["summary"]["by_language"].items():
        print(line(language, stats))


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure retrieval recall@1/@3/@8 on the eval dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=None, help="Write the full report as JSON.")
    parser.add_argument(
        "--language",
        default=None,
        help="Comma-separated case languages to measure (e.g. bm,mixed). Default: all.",
    )
    parser.add_argument(
        "--mode",
        choices=("semantic", "retriever"),
        default="semantic",
        help="`semantic` searches vectors only; `retriever` tries the exact section lookup first.",
    )
    args = parser.parse_args()

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))["cases"]
    if args.language:
        wanted = {value.strip() for value in args.language.split(",") if value.strip()}
        cases = [case for case in cases if case.get("language", "en") in wanted]
    if not cases:
        parser.error("No cases matched --language")

    report = measure(cases, args.mode)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
