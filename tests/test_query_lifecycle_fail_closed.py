import unittest
from unittest.mock import patch

from agent.query_lifecycle import run_query
from agent.query_policy import FINAL_FAILURE_RESPONSE


class QueryLifecycleFailClosedTests(unittest.TestCase):
    def test_returns_safe_fallback_when_violations_remain_after_retry(self):
        final_state = {
            "query_type": "topical",
            "final_response": "You should do X.",
            "draft_response": "You should do X.",
            "citations": [],
            "violations": ["Contains specific advice phrases."],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertEqual(result["response"], FINAL_FAILURE_RESPONSE)
        self.assertEqual(result["violations"], ["Contains specific advice phrases."])

    def test_returns_retry_answer_when_retry_clears_violations(self):
        final_state = {
            "query_type": "topical",
            "final_response": "Section 1 of Example Act applies.",
            "draft_response": "Section 1 of Example Act applies.",
            "citations": [],
            "violations": [],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertEqual(result["response"], "Section 1 of Example Act applies.")
        self.assertEqual(result["violations"], [])


if __name__ == "__main__":
    unittest.main()
