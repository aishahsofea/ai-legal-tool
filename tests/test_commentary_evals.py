import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.assertions import check_tool_selection
from evals.run_evals import _load_dataset, iter_suite

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "commentary_dataset.json"


def test_commentary_eval_dataset_is_valid_and_has_positive_negative_coverage():
    cases = _load_dataset(DATASET)
    assert len(cases) == 5
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["scenario"] for case in cases} == {
        "commentary_positive",
        "commentary_negative",
    }
    assert all(case["requires_web_commentary"] for case in cases)
    json.loads(DATASET.read_text(encoding="utf-8"))


def test_positive_eval_contract_requires_anchor_before_commentary():
    cases = _load_dataset(DATASET)
    positives = [case for case in cases if case["scenario"] == "commentary_positive"]
    assert positives
    for case in positives:
        anchor = case["expected_tool_sequence"][0]
        assert check_tool_selection(
            [anchor, "search_commentary"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
        ) is None
        # Commentary before its anchor fails the ordered-subsequence contract.
        assert check_tool_selection(
            ["search_commentary", anchor],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
        ) is not None


def test_negative_eval_contract_forbids_search_commentary():
    cases = _load_dataset(DATASET)
    negatives = [case for case in cases if case["scenario"] == "commentary_negative"]
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
            [*ordinary_trace, "search_commentary"],
            case.get("expected_tool"),
            case.get("expected_tool_sequence"),
            case.get("forbidden_tools"),
            case.get("max_tool_calls"),
        ) is not None


def test_commentary_eval_dataset_fails_fast_when_required_flags_are_off():
    cases = _load_dataset(DATASET)
    with patch.dict(os.environ, {
        "AGENTIC_RETRIEVAL": "",
        "WEB_COMMENTARY_ENABLED": "",
    }), patch("evals.run_evals.psycopg2.connect") as connect:
        iterator = iter_suite("full", cases)
        with pytest.raises(ValueError, match="requires AGENTIC_RETRIEVAL"):
            next(iterator)
    connect.assert_not_called()
