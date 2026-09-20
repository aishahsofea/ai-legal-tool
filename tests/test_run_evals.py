import os
from unittest.mock import patch

import pytest

from evals.run_evals import iter_suite


CASE = {
    "id": "case-1",
    "category": "citation",
    "scenario": "exact_match",
    "query": "What does section 90A provide?",
    "expected_act_number": "56",
    "expected_section": "90A",
    "citation_applicable": True,
    "expected_policy": "allow",
}


def test_iter_suite_fails_fast_when_the_eval_corpus_is_missing_a_required_section():
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example"}), patch(
        "evals.run_evals.present_section_pairs", return_value=set()
    ), patch("evals.run_evals.psycopg2.connect") as connect:
        iterator = iter_suite("full", [CASE])
        with pytest.raises(ValueError, match="missing 1 required section"):
            next(iterator)
    connect.assert_not_called()


def test_iter_suite_proceeds_to_connect_when_the_corpus_already_has_every_required_section():
    class _ConnectedPastTheGate(Exception):
        pass

    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://example"}), patch(
        "evals.run_evals.present_section_pairs", return_value={("56", "90A")}
    ), patch("evals.run_evals.psycopg2.connect", side_effect=_ConnectedPastTheGate):
        iterator = iter_suite("full", [CASE])
        with pytest.raises(_ConnectedPastTheGate):
            next(iterator)
