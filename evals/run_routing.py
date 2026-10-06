"""Run the real router over evals/routing_dataset.json, one query per line.

Live API: needs the credentials for ROUTER_MODEL. No database. Set ROUTER_MODEL to compare models.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from agent.nodes.router import router_node
from agent.nodes.router_jev import route_path_observer
from evals.run_evals import _initial_state
from evals.routing_summary import miss_direction, summarise

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "routing_dataset.json"
DEFAULT_RESULTS_PATH = Path(__file__).resolve().parent / "results" / "routing.json"


def _route(case: dict[str, Any]) -> dict[str, Any]:
    """The one seam to the router. Swap only this to score another classifier."""
    state = _initial_state(case["query"], case.get("history"))
    paths: list[str] = []
    token = route_path_observer.set(paths.append)
    try:
        out = router_node(state)
    finally:
        route_path_observer.reset(token)
    # Escalation answers before any model, so it reports nothing and counts as the LLM router.
    return {**out, "route_path": paths[-1] if paths else "llm"}


def score_case(
    case: dict[str, Any], route: Callable[[dict[str, Any]], dict[str, Any]], repeat: int
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": case["id"],
        "case": case,
        "repeat": repeat,
        "tags": case.get("tags", []),
        "label_type": case["query_type"],
        "label_language": case["language"],
    }
    try:
        out = route(case)
    except Exception as exc:
        # One failed call must show as an error, not abort the run or count as a miss.
        entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return entry
    got = out["query_type"]
    if got == "escalate":
        entry["error"] = "escalation regex matched; dataset must not contain it"
        return entry
    entry.update(
        query_type=got,
        response_language=out["response_language"],
        type_match=got == case["query_type"],
        language_match=out["response_language"] == case["language"],
        miss_direction=miss_direction(case["query_type"], got),
        route_path=out.get("route_path", "llm"),
    )
    return entry


def _split(value: str | list[str] | None) -> set[str]:
    parts = [value] if isinstance(value, str) else value or []
    return {item.strip() for part in parts for item in part.split(",") if item.strip()}


def select_routing_cases(
    cases: list[dict[str, Any]],
    *,
    case_ids: str | None = None,
    language: str | None = None,
    query_type: str | None = None,
    tags: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = cases
    if wanted := _split(case_ids):
        if unknown := sorted(wanted - {case["id"] for case in cases}):
            raise ValueError(f"Unknown case ids: {', '.join(unknown)}")
        selected = [case for case in selected if case["id"] in wanted]
    if wanted := _split(language):
        selected = [case for case in selected if case["language"] in wanted]
    if wanted := _split(query_type):
        selected = [case for case in selected if case["query_type"] in wanted]
    if wanted := _split(tags):
        selected = [case for case in selected if wanted & set(case.get("tags", []))]
    if limit:
        selected = selected[:limit]
    if not selected:
        raise ValueError("Routing subset matched no cases")
    return selected


def _print_group(title: str, groups: dict[str, dict[str, Any]]) -> None:
    if not groups:
        return
    print(f"\n{title}")
    for name, g in groups.items():
        print(f"  {name:<24} n={g['n']:<3} type {g['type_accuracy']:.1%}  lang {g['language_accuracy']:.1%}")


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"\nquery_type {summary['query_type_accuracy']:.1%}  language {summary['language_accuracy']:.1%}"
          f"  ({summary['total_cases']} cases, {summary['total_runs']} runs, {summary['errors']} errors)")
    if summary["by_error"]:
        print(f"Errors: {summary['by_error']}")
    print("\nConfusion (label -> predicted)")
    for label, row in summary["confusion"].items():
        print(f"  {label:<22} {row}")
    _print_group("By tag", summary["by_tag"])
    _print_group("By language", summary["by_language"])
    _print_group("By query_type", summary["by_query_type"])
    print(f"\nRoute paths: {summary['by_path']}")
    print(f"Miss directions: {summary['miss_directions']}")
    if (agreement := summary["agreement"]) is not None:
        print(f"Agreement: {agreement['agree']}/{agreement['cases']} = {agreement['rate']:.1%}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    # Evals measure the LLM router unless the caller asks for Jev: ROUTER_JEV_ENABLED=on on the command line.
    os.environ.setdefault("ROUTER_JEV_ENABLED", "off")
    parser = argparse.ArgumentParser(description="Run the router over the routing dataset.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--case-id", help="One case id.")
    parser.add_argument("--case-ids", help="Comma-separated case ids.")
    parser.add_argument("--language", help="Comma-separated labelled languages, e.g. bm,mixed.")
    parser.add_argument("--query-type", help="Comma-separated labelled types, e.g. clarify,topical.")
    parser.add_argument("--tag", action="append",
                        help="Repeatable or comma-separated; a case matches if it has any listed tag.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repeats", type=int, default=1, help="Run every case N times to measure stability.")
    parser.add_argument("--jsonl", action="store_true", help="Emit one JSON object per completed run")
    args = parser.parse_args(argv)

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))["cases"]
    try:
        selected = select_routing_cases(
            cases,
            case_ids=args.case_ids or args.case_id,
            language=args.language,
            query_type=args.query_type,
            tags=args.tag,
            limit=args.limit,
        )
    except ValueError as exc:
        parser.error(str(exc))

    results = []
    for repeat in range(max(args.repeats, 1)):
        for case in selected:
            entry = score_case(case, _route, repeat)
            results.append(entry)
            if args.jsonl:
                print(json.dumps(entry, ensure_ascii=False), flush=True)
            else:
                shown = entry.get("query_type") or f"ERROR {entry.get('error', '')}"
                miss = "" if not entry.get("miss_direction") else f" MISS ({entry['miss_direction']})"
                print(f"{case['id']}#{repeat}: label {entry['label_type']}, got {shown}{miss}", flush=True)

    summary = summarise(results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not args.jsonl:
        _print_summary(summary)
        print(f"Results written to: {args.output}")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
