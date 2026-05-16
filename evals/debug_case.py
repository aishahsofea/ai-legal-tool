"""Single-case node-by-node tracer for diagnosing FINAL_FAILURE_RESPONSE.

Usage:
    python -m evals.debug_case                            # runs penal-420-1
    python -m evals.debug_case --case pdpa-12-1
    python -m evals.debug_case --case ambiguous-defamation-scope-1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.grounding_check import grounding_check_node
from agent.nodes.retriever import retriever_node
from agent.nodes.router import router_node
from agent.nodes.supervisor import supervisor_node
from agent.nodes.synthesiser import synthesiser_node
from agent.query_policy import FINAL_FAILURE_RESPONSE, MAX_RETRIES

DATASET = Path(__file__).parent / "dataset.json"

SEP = "-" * 60


def _load_case(case_id: str) -> dict:
    data = json.loads(DATASET.read_text())
    for c in data["cases"]:
        if c["id"] == case_id:
            return c
    raise ValueError(f"Case {case_id!r} not found in dataset.")


def _initial_state(query: str) -> dict:
    return {
        "query": query,
        "history": [],
        "query_type": "",
        "response_language": "en",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }


def _print_violations(label: str, violations: list[str]) -> None:
    if violations:
        print(f"  *** {label} violations ({len(violations)}):")
        for v in violations:
            print(f"      - {v}")
    else:
        print(f"  {label}: no violations")


def run_debug(case_id: str) -> None:
    case = _load_case(case_id)
    query = case["query"]

    print(SEP)
    print(f"CASE    : {case_id}")
    print(f"QUERY   : {query}")
    print(f"EXPECTS : Act {case.get('expected_act_number')} s{case.get('expected_section')}")
    print(f"POLICY  : {case.get('expected_policy', 'allow')}")
    print(SEP)

    state = _initial_state(query)

    # --- Router ---
    print("\n[1] ROUTER")
    state.update(router_node(state))
    print(f"  query_type       : {state['query_type']}")
    print(f"  response_language: {state['response_language']}")

    if state["query_type"] == "escalate":
        print("\n  !! Router escalated — graph would end here with ESCALATION_RESPONSE.")
        return

    # --- Retriever ---
    print("\n[2] RETRIEVER")
    state.update(retriever_node(state))
    chunks = state["retrieved_chunks"]
    print(f"  chunks retrieved : {len(chunks)}")
    for c in chunks:
        print(f"    Act {c.get('act_number')} s{c.get('section_number')} — {c.get('act_title', '')[:50]}")

    for attempt in range(1, MAX_RETRIES + 2):  # original + retries
        print(f"\n{'[3]' if attempt == 1 else '[RETRY]'} SYNTHESISER (attempt {attempt})")
        state.update(synthesiser_node(state))
        draft = state["draft_response"]
        print(f"  draft length     : {len(draft)} chars")
        print(f"  citations        : {[(c['act_number'], c['section_number']) for c in state['citations']]}")
        print(f"  draft preview    :\n{draft[:600]}")

        print(f"\n{'[4]' if attempt == 1 else '[RETRY]'} CITATION VALIDATOR (attempt {attempt})")
        state.update(citation_validator_node(state))
        _print_violations("citation_validator", state["violations"])

        print(f"\n{'[5]' if attempt == 1 else '[RETRY]'} GROUNDING CHECK (attempt {attempt})")
        pre_grounding_violations = list(state["violations"])
        state.update(grounding_check_node(state))
        new_grounding = [v for v in state["violations"] if v not in pre_grounding_violations]
        _print_violations("grounding_check (new)", new_grounding)

        print(f"\n{'[6]' if attempt == 1 else '[RETRY]'} SUPERVISOR (attempt {attempt})")
        pre_supervisor_violations = list(state["violations"])
        state.update(supervisor_node(state))
        new_supervisor = [v for v in state["violations"] if v not in pre_supervisor_violations]
        _print_violations("supervisor (new)", new_supervisor)

        if not state["violations"]:
            print(f"\n{'='*60}")
            print("RESULT: PASS — no violations, response would be returned.")
            print(f"{'='*60}")
            return

        if attempt <= MAX_RETRIES:
            print(f"\n  -> violations persist, triggering retry (retry_count={attempt})")
            state["retry_count"] = attempt
            state["violations"] = []
        else:
            break

    print(f"\n{'='*60}")
    print("RESULT: FAIL — violations persisted after all retries.")
    print(f"  Final violations ({len(state['violations'])}):")
    for v in state["violations"]:
        print(f"    - {v}")
    print(f"\n  _fail_closed_if_violations would return:\n  '{FINAL_FAILURE_RESPONSE}'")
    print(f"{'='*60}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="penal-420-1")
    args = parser.parse_args()
    run_debug(args.case)


if __name__ == "__main__":
    main()
