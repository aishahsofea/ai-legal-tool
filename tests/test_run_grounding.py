from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.jev_client import JevError
from evals import run_grounding

CASE = {
    "id": "g1", "verdict": "unsupported", "language": "en", "claim": "Claim.",
    "act_number": "56", "act_title": "EVIDENCE ACT 1950", "section_number": "1",
    "source_text": "1. Text.",
}


def _judge(*supports):
    claims = [SimpleNamespace(support=s, reason=f"why {s}", quote=f"q {s}") for s in supports]
    return patch.object(run_grounding, "judge_claims", return_value=SimpleNamespace(claims=claims))


def _jev(enabled, score=None, error=False):
    def probability(*_args):
        if error:
            raise JevError("boom")
        return score

    return (
        patch.object(run_grounding, "_jev_enabled", return_value=enabled),
        patch.object(run_grounding, "supported_probability", side_effect=probability),
        patch.object(run_grounding, "_jev_threshold", return_value=0.97),
    )


def _run(case, judge, jev):
    with judge, jev[0], jev[1], jev[2]:
        return run_grounding.judge_case(case)


def test_match_when_judge_label_equals_verdict():
    result = _run(CASE, _judge("unsupported"), _jev(False))

    assert result["match"] is True
    assert result["error_kind"] is None
    assert result["judge_label"] == "unsupported"
    assert result["reason"] == "why unsupported"
    assert result["quote"] == "q unsupported"


@pytest.mark.parametrize(
    ("verdict", "judge_label", "kind"),
    [
        ("unsupported", "supported", "too_lenient"),
        ("unsupported", "partial", "too_lenient"),
        ("partial", "supported", "too_lenient"),
        ("supported", "unsupported", "too_strict"),
        ("supported", "partial", "too_strict"),
        ("partial", "unsupported", "too_strict"),
    ],
)
def test_mismatch_kinds(verdict, judge_label, kind):
    result = _run({**CASE, "verdict": verdict}, _judge(judge_label), _jev(False))

    assert result["match"] is False
    assert result["error_kind"] == kind


def test_jev_clear_skips_the_judge_and_counts_as_supported():
    with patch.object(run_grounding, "judge_claims", side_effect=AssertionError("judge called")):
        result = _run({**CASE, "verdict": "supported"}, patch.object(run_grounding, "draft"), _jev(True, 0.99))

    assert result["jev_cleared"] is True
    assert result["jev_score"] == 0.99
    assert result["judge_label"] == "supported"
    assert result["match"] is True
    assert result["reason"] == "Jev cleared, judge skipped"


def test_jev_clear_on_an_unsupported_claim_is_too_lenient():
    result = _run(CASE, _judge("unsupported"), _jev(True, 0.99))

    assert result["error_kind"] == "too_lenient"


def test_jev_below_threshold_falls_through_to_the_judge():
    result = _run(CASE, _judge("unsupported"), _jev(True, 0.5))

    assert result["jev_cleared"] is False
    assert result["jev_score"] == 0.5
    assert result["judge_label"] == "unsupported"


def test_jev_error_falls_through_to_the_judge():
    result = _run(CASE, _judge("unsupported"), _jev(True, error=True))

    assert result["jev_error"] is True
    assert result["jev_score"] is None
    assert result["judge_label"] == "unsupported"
    assert result["match"] is True


def test_weakest_claim_label_decides():
    result = _run(CASE, _judge("supported", "partial"), _jev(False))

    assert result["judge_label"] == "partial"
    assert result["claims_found"] == 2


def test_no_extracted_claim_is_supported_like_production():
    result = _run({**CASE, "verdict": "supported"}, _judge(), _jev(False))

    assert result["judge_label"] == "supported"
    assert result["claims_found"] == 0
    assert result["match"] is True


def test_judge_failure_is_recorded_not_passed():
    with patch.object(run_grounding, "judge_claims", side_effect=RuntimeError("down")):
        result = _run(CASE, patch.object(run_grounding, "draft"), _jev(False))

    assert result["match"] is False
    assert result["judge_label"] is None
    assert "down" in result["error"]


def test_selection_filters_and_rejects_unknown_ids():
    cases = [
        {**CASE, "id": "a"},
        {**CASE, "id": "b", "verdict": "supported", "language": "bm", "judgement_call": True},
    ]

    assert [c["id"] for c in run_grounding.select_grounding_cases(cases, case_ids="b")] == ["b"]
    assert [c["id"] for c in run_grounding.select_grounding_cases(cases, verdict="unsupported")] == ["a"]
    assert [c["id"] for c in run_grounding.select_grounding_cases(cases, language="bm")] == ["b"]
    assert [c["id"] for c in run_grounding.select_grounding_cases(cases, judgement_call=True)] == ["b"]
    assert [c["id"] for c in run_grounding.select_grounding_cases(cases, limit=1)] == ["a"]
    with pytest.raises(ValueError, match="Unknown case ids: zz"):
        run_grounding.select_grounding_cases(cases, case_ids="zz")
    with pytest.raises(ValueError, match="no cases"):
        run_grounding.select_grounding_cases(cases, verdict="partial")
