"""Run the eval suite against the live agent graph."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.graph import ESCALATION_RESPONSE, graph
from agent.nodes.retriever import retriever_node
from agent.nodes.router import router_node
from agent.nodes.synthesiser import synthesiser_node
from evals.judge import JudgeContext, judge_case

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = ROOT / "dataset.json"
DEFAULT_RESULTS_PATH = ROOT / "results.json"


def _initial_state(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "query_type": "",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }


def _run_full_agent(query: str) -> dict[str, Any]:
    return graph.invoke(_initial_state(query))


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
        "retrieved_sections": [
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


def run_suite(mode: str, dataset_path: Path, limit: int | None = None) -> dict[str, Any]:
    cases = _maybe_limit(_load_dataset(dataset_path), limit)
    results: list[dict[str, Any]] = []

    citation_total = 0
    citation_passed = 0
    policy_total = len(cases)
    policy_passed = 0

    runner_map = {
        "full": _run_full_agent,
        "raw": _run_raw_agent,
        "baseline": _run_baseline_agent,
    }
    runner = runner_map[mode]

    for idx, case in enumerate(cases, 1):
        query = case["query"]
        print(f"[{idx}/{len(cases)}] {case['id']} ...", flush=True)
        started = time.perf_counter()

        agent_state = runner(query)
        agent_output = _compact_state(agent_state)

        verdict = judge_case(
            JudgeContext(
                query=query,
                agent_response=agent_output["final_response"],
                citations=agent_output["citations"],
                violations=agent_output["violations"],
                expected_act_number=case.get("expected_act_number"),
                expected_section=case.get("expected_section"),
                expected_policy=case.get("expected_policy", "allow"),
            )
        )

        citation_applicable = bool(case.get("citation_applicable", False))
        if citation_applicable:
            citation_total += 1
            citation_passed += int(bool(verdict.citation_accuracy))
        policy_passed += int(verdict.policy_compliance)

        elapsed = time.perf_counter() - started
        print(
            f"    done in {elapsed:.1f}s | cite={int(bool(verdict.citation_accuracy)) if verdict.citation_accuracy is not None else 'n/a'} | policy={int(verdict.policy_compliance)}",
            flush=True,
        )

        results.append(
            {
                "case": case,
                "agent": agent_output,
                "judge": verdict.model_dump(),
            }
        )

    summary = {
        "mode": mode,
        "total_cases": len(cases),
        "citation_applicable_cases": citation_total,
        "citation_passed": citation_passed,
        "citation_pass_rate": _rate(citation_passed, citation_total),
        "policy_passed": policy_passed,
        "policy_pass_rate": _rate(policy_passed, policy_total),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run evals against the agent graph.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--mode", choices=("full", "raw", "baseline"), default="full")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fail-under", type=float, default=0.8)
    args = parser.parse_args()

    print(
        f"Running evals in {args.mode} mode on {args.limit or 'all'} cases...",
        flush=True,
    )
    print("This can take a while: each case runs the live agent and then Claude-as-judge.", flush=True)
    report = run_suite(args.mode, args.dataset, args.limit)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"Mode: {summary['mode']}")
    print(f"Cases: {summary['total_cases']}")
    print(f"Citation accuracy: {summary['citation_passed']}/{summary['citation_applicable_cases']} = {summary['citation_pass_rate']:.1%}")
    print(f"Policy compliance: {summary['policy_passed']}/{summary['total_cases']} = {summary['policy_pass_rate']:.1%}")
    print(f"Results written to: {args.output}")

    if summary["citation_pass_rate"] < args.fail_under or summary["policy_pass_rate"] < args.fail_under:
        print(f"Failing because one metric is below {args.fail_under:.0%}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
