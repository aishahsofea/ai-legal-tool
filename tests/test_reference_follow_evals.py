import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.retrieval.reference_graph import should_follow_references
from evals.assertions import check_tool_selection
from evals.run_evals import _compact_state, _load_dataset, _run_full_agent, iter_suite


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "reference_follow_dataset.json"


def test_reference_follow_eval_dataset_is_valid_and_has_positive_negative_coverage():
    cases = _load_dataset(DATASET)
    assert len(cases) == 7
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["scenario"] for case in cases} == {
        "reference_follow_positive",
        "reference_follow_incoming",
        "reference_follow_negative",
    }
    assert all(case["requires_follow_references"] for case in cases)
    json.loads(DATASET.read_text(encoding="utf-8"))


def test_reference_follow_eval_queries_match_the_runtime_selective_intent_gate():
    cases = _load_dataset(DATASET)
    for case in cases:
        expected = case["scenario"] != "reference_follow_negative"
        assert should_follow_references(case["query"]) is expected, case["id"]


def test_positive_eval_contract_requires_anchor_before_one_follow():
    cases = _load_dataset(DATASET)
    positives = [
        case for case in cases
        if case.get("expected_tool_sequence")
    ]
    assert positives
    for case in positives:
        assert check_tool_selection(
            ["lookup_section", "follow_references"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
            [{
                "status": "followed",
                "direction": case["expected_reference_direction"],
            }],
            case.get("expected_reference_direction"),
        ) is None
        assert check_tool_selection(
            ["follow_references", "lookup_section"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
            [],
            case.get("expected_reference_direction"),
        ) is not None
        assert check_tool_selection(
            ["lookup_section", "follow_references", "follow_references"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
            [{
                "status": "followed",
                "direction": case["expected_reference_direction"],
            }],
            case.get("expected_reference_direction"),
        ) is not None


def test_positive_eval_contract_rejects_the_wrong_follow_direction():
    incoming = next(
        case
        for case in _load_dataset(DATASET)
        if case["scenario"] == "reference_follow_incoming"
    )
    failure = check_tool_selection(
        ["lookup_section", "follow_references"],
        incoming.get("expected_tool"),
        incoming.get("expected_tool_sequence"),
        incoming.get("forbidden_tools"),
        incoming.get("max_tool_calls"),
        [{"status": "followed", "direction": "outgoing"}],
        incoming["expected_reference_direction"],
    )
    assert "direction `incoming`" in failure


def test_live_eval_adapter_preserves_enabled_reference_trace_for_assertions():
    trace = [{
        "status": "followed",
        "reason": "followed",
        "direction": "incoming",
    }]
    with patch("evals.run_evals.run_query", return_value={
        "query_type": "statute_lookup",
        "response": "Fixture response.",
        "citations": [],
        "violations": [],
        "tool_trace": ["lookup_section", "follow_references"],
        "reference_trace": trace,
    }):
        state = _run_full_agent("Which provisions refer to section 60D?")
    compact = _compact_state(state)
    assert compact["reference_trace"] == trace


def test_negative_eval_contract_forbids_follow_references():
    cases = _load_dataset(DATASET)
    negatives = [
        case for case in cases
        if case["scenario"] == "reference_follow_negative"
    ]
    assert negatives
    for case in negatives:
        ordinary_trace = [case["expected_tool"]] if case.get("expected_tool") else []
        assert check_tool_selection(
            ordinary_trace,
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
        ) is None
        assert check_tool_selection(
            [*ordinary_trace, "follow_references"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
        ) is not None


def test_follow_eval_dataset_fails_fast_when_required_flags_are_off():
    cases = _load_dataset(DATASET)
    with patch.dict(os.environ, {
        "AGENTIC_RETRIEVAL": "",
        "FOLLOW_REFERENCES_ENABLED": "",
    }), patch("evals.run_evals.psycopg2.connect") as connect:
        iterator = iter_suite("full", cases)
        with pytest.raises(ValueError, match="requires AGENTIC_RETRIEVAL"):
            next(iterator)
    connect.assert_not_called()
