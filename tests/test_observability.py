"""Unit tests for LangSmith feedback (agent/observability.py) and the _config
metadata/tags additions. build_feedback is pure; emit_feedback must fail open."""
import unittest
from unittest.mock import MagicMock, patch

from agent.observability import build_feedback, emit_feedback, root_run_id
from agent.query_lifecycle import _config
from agent.query_policy import FINAL_FAILURE_RESPONSE


class BuildFeedbackTests(unittest.TestCase):
    def test_clean_pass(self):
        fb = build_feedback({
            "query_type": "topical",
            "violations": [],
            "evidence_violations": [],
            "citations": [{"act_number": "1"}, {"act_number": "2"}],
            "retry_count": 0,
            "final_response": "Section 1 applies.",
        })
        self.assertEqual(fb["passed"], 1.0)
        self.assertEqual(fb["num_violations"], 0.0)
        self.assertEqual(fb["num_citations"], 2.0)
        self.assertEqual(fb["fallback_delivered"], 0.0)
        self.assertEqual(fb["escalated"], 0.0)
        self.assertEqual(fb["query_type"], "topical")

    def test_violations_and_fallback(self):
        # Unresolved violations => delivered_response is the safe fallback.
        fb = build_feedback({
            "query_type": "topical",
            "violations": ["advice phrase", "missing disclaimer"],
            "evidence_violations": ["unsupported claim"],
            "citations": [],
            "retry_count": 1,
            "final_response": "You should do X.",
        })
        self.assertEqual(fb["passed"], 0.0)
        self.assertEqual(fb["num_violations"], 2.0)
        self.assertEqual(fb["num_evidence_violations"], 1.0)
        self.assertEqual(fb["retry_count"], 1.0)
        self.assertEqual(fb["fallback_delivered"], 1.0)

    def test_escalation(self):
        fb = build_feedback({"query_type": "escalate", "final_response": "..."})
        self.assertEqual(fb["escalated"], 1.0)
        self.assertEqual(fb["query_type"], "escalate")

    def test_missing_fields_default_safely(self):
        # A near-empty state must not raise (defensive for error/empty turns).
        fb = build_feedback({})
        self.assertEqual(fb["passed"], 1.0)
        self.assertEqual(fb["num_citations"], 0.0)


class EmitFeedbackTests(unittest.TestCase):
    def test_noop_when_tracing_disabled(self):
        # No client constructed, no raise, when tracing is off.
        with patch("agent.observability._tracing_enabled", return_value=False), \
             patch("agent.observability._client") as client:
            emit_feedback("run-123", {"violations": []})
        client.assert_not_called()

    def test_noop_when_run_id_missing(self):
        with patch("agent.observability._tracing_enabled", return_value=True), \
             patch("agent.observability._client") as client:
            emit_feedback(None, {"violations": []})
        client.assert_not_called()

    def test_posts_scores_and_categorical_with_trace_id(self):
        mock_client = MagicMock()
        with patch("agent.observability._tracing_enabled", return_value=True), \
             patch("agent.observability._client", return_value=mock_client):
            emit_feedback("run-123", {"query_type": "topical", "violations": []})

        self.assertTrue(mock_client.create_feedback.called)
        # Every call must carry trace_id=run_id (routes to the non-blocking batch).
        for call in mock_client.create_feedback.call_args_list:
            self.assertEqual(call.kwargs.get("trace_id"), "run-123")
        # query_type goes out as a categorical `value`, not a numeric `score`.
        qt = [c for c in mock_client.create_feedback.call_args_list if c.kwargs.get("key") == "query_type"]
        self.assertEqual(len(qt), 1)
        self.assertEqual(qt[0].kwargs.get("value"), "topical")
        self.assertNotIn("score", qt[0].kwargs)

    def test_client_error_is_swallowed(self):
        mock_client = MagicMock()
        mock_client.create_feedback.side_effect = RuntimeError("boom")
        with patch("agent.observability._tracing_enabled", return_value=True), \
             patch("agent.observability._client", return_value=mock_client):
            emit_feedback("run-123", {"violations": []})  # must not raise


class RootRunIdTests(unittest.TestCase):
    def test_none_collector(self):
        self.assertIsNone(root_run_id(None))

    def test_picks_parentless_run(self):
        child = MagicMock(id="child", parent_run_id="root")
        root = MagicMock(id="root-id", parent_run_id=None)
        collector = MagicMock(traced_runs=[child, root])
        self.assertEqual(root_run_id(collector), "root-id")

    def test_empty_traced_runs(self):
        self.assertIsNone(root_run_id(MagicMock(traced_runs=[])))


class ConfigTests(unittest.TestCase):
    def test_includes_metadata_tags_run_name(self):
        cfg = _config("t1", "u1")
        self.assertEqual(cfg["run_name"], "legal_query")
        self.assertEqual(cfg["metadata"]["user_id"], "u1")
        self.assertEqual(cfg["metadata"]["thread_id"], "t1")
        self.assertIn("legal_query", cfg["tags"])
        self.assertIn("source:api", cfg["tags"])

    def test_configurable_unchanged(self):
        # Regression guard: the memory path reads thread_id/user_id from configurable.
        cfg = _config("t1", "u1")
        self.assertEqual(cfg["configurable"], {"thread_id": "t1", "user_id": "u1"})

    def test_anonymous_user_and_source(self):
        cfg = _config("t1", None, source="eval")
        self.assertEqual(cfg["metadata"]["user_id"], "anonymous")
        self.assertEqual(cfg["metadata"]["source"], "eval")
        self.assertIn("source:eval", cfg["tags"])

    def test_collector_added_to_callbacks(self):
        sentinel = object()
        cfg = _config("t1", "u1", sentinel)
        self.assertEqual(cfg["callbacks"], [sentinel])

    def test_no_callbacks_key_without_collector(self):
        self.assertNotIn("callbacks", _config("t1", "u1"))


if __name__ == "__main__":
    unittest.main()
