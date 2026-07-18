"""Run the eval suite against the live agent graph."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Any

import psycopg2
from dotenv import load_dotenv

from agent.graph import ESCALATION_RESPONSE
from agent.nodes.retriever import retriever_node
from agent.nodes.router import router_node
from agent.nodes.synthesiser import synthesiser_node
from agent.query_lifecycle import run_query
from evals.assertions import BM_FUNCTION_WORDS, run_assertions
from evals.coverage import aggregate_scenarios, select_cases
from evals.judge import JudgeContext, judge_case

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = ROOT / "dataset.json"
DEFAULT_RESULTS_PATH = ROOT / "results.json"

_ASSERTION_NAMES = [
    "citation_existence",
    "tool_selection",
    "expected_section",
    "language_register",
    "uuid_leakage",
    "ai_refusal",
]


def _initial_state(query: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "query": query,
        "history": history or [],
        "query_type": "",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }


def _run_full_agent(query: str, history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    # Conversation memory is now server-side, keyed by thread_id. Each eval case is
    # an independent single-turn query, so use a fresh thread_id (dataset cases carry
    # no prior history; multi-turn eval seeding would replay turns on one thread_id).
    result = run_query(query, uuid.uuid4().hex)
    return {
        "query_type": result["query_type"],
        "final_response": result["response"],
        "citations": result["citations"],
        "violations": result["violations"],
        "retry_count": 0,
        "retrieved_chunks": [],
        "tool_trace": result.get("tool_trace", []),
    }


def _run_raw_agent(query: str) -> dict[str, Any]:
    state = _initial_state(query)
    state.update(router_node(state))

    if state.get("query_type") == "escalate":
        state["final_response"] = ESCALATION_RESPONSE
        state["violations"] = []
        state["citations"] = []
        return state

    state.update(retriever_node(state))
    state.update(synthesiser_node(state))
    return state


def _run_baseline_agent(query: str) -> dict[str, Any]:
    state = _initial_state(query)
    state["query_type"] = "statute_lookup"
    state.update(retriever_node(state))
    state.update(synthesiser_node(state))
    return state


def _response_text(state: dict[str, Any]) -> str:
    return state.get("final_response") or state.get("draft_response") or ""


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_type": state.get("query_type", ""),
        "final_response": _response_text(state),
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
        "retry_count": state.get("retry_count", 0),
        "tool_trace": state.get("tool_trace", []),
        "retrieved_chunks": [
            {
                "act_number": c.get("act_number"),
                "section_number": c.get("section_number"),
                "act_title": c.get("act_title"),
            }
            for c in state.get("retrieved_chunks", [])[:8]
        ],
    }


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


def _maybe_limit(cases: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return cases
    return cases[:limit]


def _rate(passed: int, total: int) -> float:
    return 0.0 if total == 0 else passed / total


def serialize_case_result(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a persisted eval result into the dashboard's JSONL event shape."""
    case = result["case"]
    agent = result["agent"]
    failure_details = result.get("l1_failures", {})
    return {
        "id": case["id"],
        "category": case["category"],
        "scenario": case["scenario"],
        "expected_policy": case.get("expected_policy", "allow"),
        "expected_act_number": case.get("expected_act_number"),
        "expected_section": case.get("expected_section"),
        "l1_failures": list(failure_details),
        "l1_failure_details": failure_details,
        "judge": result.get("judge"),
        "query": case["query"],
        "response": agent.get("final_response", ""),
        "citations": agent.get("citations", []),
        "elapsed_seconds": result.get("elapsed_seconds", 0.0),
    }


def _assertion_applicable(
    name: str,
    *,
    citations: list[dict[str, Any]],
    query: str,
    expected_act_number: str | None,
    expected_section: str | None,
    expected_policy: str,
    expected_tool: str | None = None,
) -> bool:
    if name == "citation_existence":
        return bool(citations)
    if name == "tool_selection":
        return bool(expected_tool)
    if name == "expected_section":
        return bool(expected_act_number and expected_section)
    if name == "language_register":
        return any(w in query.lower() for w in BM_FUNCTION_WORDS)
    if name == "uuid_leakage":
        return True
    if name == "ai_refusal":
        return expected_policy == "allow"
    return False


def iter_suite(
    mode: str,
    cases: list[dict[str, Any]],
    *,
    on_case_start: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Run cases synchronously and yield each completed result immediately."""
    runner_map = {
        "full": _run_full_agent,
        "raw": _run_raw_agent,
        "baseline": _run_baseline_agent,
    }
    runner = runner_map[mode]

    # tool_selection only applies to the agentic retriever (it's the only path that
    # produces a tool trace). With the flag off, expected_tool is treated as absent
    # so the assertion is skipped and the default eval is unaffected.
    agentic_on = os.getenv("AGENTIC_RETRIEVAL", "").lower() in ("1", "true", "yes")

    db_conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        for idx, case in enumerate(cases, 1):
            query = case["query"]
            if on_case_start:
                on_case_start(idx, len(cases), case)
            started = time.perf_counter()

            history = case.get("history", [])
            agent_state = runner(query, history) if mode == "full" else runner(query)
            agent_output = _compact_state(agent_state)

            citations = agent_output["citations"]
            response = agent_output["final_response"]
            tool_trace = agent_output.get("tool_trace", [])
            expected_act_number = case.get("expected_act_number")
            expected_section = case.get("expected_section")
            expected_policy = case.get("expected_policy", "allow")
            expected_tool = case.get("expected_tool") if agentic_on else None

            applicable = [
                name
                for name in _ASSERTION_NAMES
                if _assertion_applicable(
                    name,
                    citations=citations,
                    query=query,
                    expected_act_number=expected_act_number,
                    expected_section=expected_section,
                    expected_policy=expected_policy,
                    expected_tool=expected_tool,
                )
            ]

            l1_failures = run_assertions(
                citations=citations,
                query=query,
                response=response,
                expected_act_number=expected_act_number,
                expected_section=expected_section,
                expected_policy=expected_policy,
                db_conn=db_conn,
                tool_trace=tool_trace,
                expected_tool=expected_tool,
            )

            case_result: dict[str, Any] = {
                "case": case,
                "agent": agent_output,
                "_l1_applicable": applicable,
            }

            if l1_failures:
                case_result["l1_failures"] = l1_failures
                case_result["judge"] = None
            else:
                verdict = judge_case(
                    JudgeContext(
                        query=query,
                        agent_response=response,
                        citations=citations,
                        violations=agent_output["violations"],
                        expected_act_number=expected_act_number,
                        expected_section=expected_section,
                        expected_policy=expected_policy,
                        retrieved_chunks=agent_output["retrieved_chunks"],
                    )
                )
                case_result["judge"] = verdict.model_dump()
            case_result["elapsed_seconds"] = time.perf_counter() - started
            yield case_result
    finally:
        db_conn.close()


def _persisted_result(result: dict[str, Any]) -> dict[str, Any]:
    persisted = {"case": result["case"], "agent": result["agent"]}
    if "l1_failures" in result:
        persisted["l1_failures"] = result["l1_failures"]
    persisted["judge"] = result.get("judge")
    return persisted


def _build_report(mode: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    l1_applicable = {name: 0 for name in _ASSERTION_NAMES}
    l1_passed = {name: 0 for name in _ASSERTION_NAMES}
    judge_total = 0
    judge_passed = 0

    for result in results:
        failures = result.get("l1_failures", {})
        for name in result.get("_l1_applicable", []):
            l1_applicable[name] += 1
            l1_passed[name] += int(name not in failures)
        verdict = result.get("judge")
        if isinstance(verdict, dict):
            judge_total += 1
            judge_passed += int(verdict.get("passed") is True)

    l1_summary = {
        name: {
            "passed": l1_passed[name],
            "total": l1_applicable[name],
            "rate": _rate(l1_passed[name], l1_applicable[name]),
        }
        for name in _ASSERTION_NAMES
    }

    summary = {
        "mode": mode,
        "total_cases": len(cases),
        "l1": l1_summary,
        "judge_passed": judge_passed,
        "judge_total": judge_total,
        "judge_pass_rate": _rate(judge_passed, judge_total),
        "by_scenario": aggregate_scenarios(serialize_case_result(result) for result in results),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": [_persisted_result(result) for result in results],
    }


def _resolve_cli_cases(
    dataset_path: Path,
    *,
    smoke: bool = False,
    category: str | None = None,
    scenario: str | None = None,
    case_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    cases = _load_dataset(dataset_path)
    subset_filters = [smoke, category is not None, scenario is not None, case_id is not None]
    if sum(subset_filters) > 1:
        raise ValueError("Choose only one of --smoke, --category, --scenario, or --case-id")
    if smoke:
        cases = select_cases(cases, "smoke")
    elif category is not None:
        cases = select_cases(cases, {"category": category})
    elif scenario is not None:
        cases = select_cases(cases, {"scenario": scenario})
    elif case_id is not None:
        cases = select_cases(cases, {"case_id": case_id})
    return _maybe_limit(cases, limit)


def run_suite(
    mode: str,
    dataset_path: Path,
    limit: int | None = None,
    smoke: bool = False,
    *,
    category: str | None = None,
    scenario: str | None = None,
    case_id: str | None = None,
    progress: bool = True,
    on_case_result: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cases = _resolve_cli_cases(
        dataset_path,
        smoke=smoke,
        category=category,
        scenario=scenario,
        case_id=case_id,
        limit=limit,
    )

    def print_start(index: int, total: int, case: dict[str, Any]) -> None:
        print(f"[{index}/{total}] {case['id']} ...", flush=True)

    results: list[dict[str, Any]] = []
    for result in iter_suite(mode, cases, on_case_start=print_start if progress else None):
        results.append(result)
        if progress:
            elapsed = result["elapsed_seconds"]
            failures = result.get("l1_failures", {})
            if failures:
                print(f"    L1 FAIL in {elapsed:.1f}s | {', '.join(failures)}", flush=True)
            else:
                verdict = result["judge"]
                print(
                    f"    done in {elapsed:.1f}s | judge={'PASS' if verdict['passed'] else 'FAIL'}",
                    flush=True,
                )
        if on_case_result:
            on_case_result(serialize_case_result(result))

    return _build_report(mode, results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run evals against the agent graph.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--mode", choices=("full", "raw", "baseline"), default="full")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--smoke", action="store_true", help="Run only smoke-tagged cases (CI regression gate)")
    parser.add_argument("--category")
    parser.add_argument("--scenario")
    parser.add_argument("--case-id")
    parser.add_argument("--jsonl", action="store_true", help="Emit one JSON object per completed case")
    parser.add_argument("--fail-under", type=float, default=0.8)
    args = parser.parse_args()

    if not args.jsonl:
        case_label = "smoke" if args.smoke else (str(args.limit) if args.limit else "all")
        print(
            f"Running evals in {args.mode} mode on {case_label} cases...",
            flush=True,
        )
        print("This can take a while: each case runs the live agent and then Claude-as-judge.", flush=True)
    try:
        report = run_suite(
            args.mode,
            args.dataset,
            args.limit,
            smoke=args.smoke,
            category=args.category,
            scenario=args.scenario,
            case_id=args.case_id,
            progress=not args.jsonl,
            on_case_result=(
                lambda result: print(json.dumps(result, ensure_ascii=False), flush=True)
                if args.jsonl else None
            ),
        )
    except ValueError as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    l1 = summary["l1"]
    if args.jsonl:
        return 0
    print(f"\nMode: {summary['mode']}")
    print(f"Cases: {summary['total_cases']}")
    print("\nL1 assertion results:")
    for name, stats in l1.items():
        print(f"  {name}: {stats['passed']}/{stats['total']} = {stats['rate']:.1%}")
    print(f"\nJudge: {summary['judge_passed']}/{summary['judge_total']} = {summary['judge_pass_rate']:.1%}")
    print(f"Results written to: {args.output}")

    citation_existence_rate = l1["citation_existence"]["rate"]
    citation_existence_total = l1["citation_existence"]["total"]
    failed = False

    if citation_existence_total > 0 and citation_existence_rate < 1.0:
        print(
            f"\nFAIL: citation_existence rate is {citation_existence_rate:.1%} "
            "(must be 100% — any hallucinated citation is disqualifying)."
        )
        failed = True

    if summary["judge_pass_rate"] < args.fail_under:
        print(
            f"\nFAIL: judge pass rate {summary['judge_pass_rate']:.1%} "
            f"is below --fail-under threshold of {args.fail_under:.0%}."
        )
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
