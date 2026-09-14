"""A skipped grounding check must be countable at the run level (issue #85).

grounding_check fails open, so a skip produces no violation and no failed
assertion. Nothing in the eval pass rate moves. These cover the two places that
make it visible anyway: the LangSmith feedback scores and the eval summary.
"""
import unittest

from agent.observability import build_feedback
from evals.run_evals import _build_report, _grounding_summary


def _result(checked: int, skipped: int) -> dict:
    return {
        "case": {"id": "c1", "category": "x", "scenario": "y", "query": "q"},
        "agent": {
            "query_type": "statute_lookup",
            "final_response": "answer",
            "citations": [],
            "violations": [],
            "retrieved_chunks": [],
            "grounding_metrics": {"checked": checked, "skipped": skipped},
        },
        "_l1_applicable": [],
        "judge": {"passed": True},
    }


class GroundingSummaryTests(unittest.TestCase):
    def test_counts_sum_across_cases(self):
        summary = _grounding_summary([_result(1, 0), _result(0, 1), _result(2, 1)])

        self.assertEqual(summary["checked"], 3)
        self.assertEqual(summary["skipped"], 2)
        self.assertEqual(summary["skip_rate"], 0.4)

    def test_modes_that_never_reach_the_node_report_zero(self):
        bare = {"case": {}, "agent": {}, "_l1_applicable": []}

        summary = _grounding_summary([bare])

        self.assertEqual(summary, {"checked": 0, "skipped": 0, "skip_rate": 0.0})

    def test_report_carries_the_summary(self):
        report = _build_report("full", [_result(1, 1)])

        self.assertEqual(report["summary"]["grounding"]["skipped"], 1)

    def test_a_skipped_check_does_not_move_the_judge_rate(self):
        """Why the counter exists: the existing numbers cannot see the skip."""
        clean = _build_report("full", [_result(1, 0)])["summary"]
        skipped = _build_report("full", [_result(0, 1)])["summary"]

        self.assertEqual(clean["judge_pass_rate"], skipped["judge_pass_rate"])
        self.assertNotEqual(clean["grounding"], skipped["grounding"])


class GroundingFeedbackTests(unittest.TestCase):
    def test_counters_reach_langsmith(self):
        feedback = build_feedback({"grounding_metrics": {"checked": 1, "skipped": 2}})

        self.assertEqual(feedback["grounding_checked"], 1.0)
        self.assertEqual(feedback["grounding_skipped"], 2.0)

    def test_missing_metrics_score_zero(self):
        feedback = build_feedback({})

        self.assertEqual(feedback["grounding_checked"], 0.0)
        self.assertEqual(feedback["grounding_skipped"], 0.0)


if __name__ == "__main__":
    unittest.main()
