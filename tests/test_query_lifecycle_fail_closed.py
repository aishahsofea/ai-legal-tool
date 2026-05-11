import unittest
from unittest.mock import patch

from agent.query_lifecycle import FINAL_FAILURE_RESPONSE, run_query


class QueryLifecycleFailClosedTests(unittest.TestCase):
    def test_returns_safe_fallback_when_violations_remain_after_retry(self):
        def fake_synthesiser(state):
            return {"draft_response": "You should do X.", "citations": []}

        def fake_supervisor(state):
            return {
                "violations": ["Contains specific advice phrases."],
                "final_response": state["draft_response"],
            }

        with patch("agent.query_lifecycle.router_node", return_value={"query_type": "topical"}), \
             patch("agent.query_lifecycle.retriever_node", return_value={"retrieved_chunks": []}), \
             patch("agent.query_lifecycle.synthesiser_node", side_effect=fake_synthesiser), \
             patch("agent.query_lifecycle.supervisor_node", side_effect=fake_supervisor):
            result = run_query("What does the law say?")

        self.assertEqual(result["response"], FINAL_FAILURE_RESPONSE)
        self.assertEqual(result["violations"], ["Contains specific advice phrases."])

    def test_returns_retry_answer_when_retry_clears_violations(self):
        def fake_synthesiser(state):
            if state.get("retry_count", 0):
                return {"draft_response": "Section 1 of Example Act applies.", "citations": []}
            return {"draft_response": "You should do X.", "citations": []}

        def fake_supervisor(state):
            if "You should" in state["draft_response"]:
                return {
                    "violations": ["Contains specific advice phrases."],
                    "final_response": state["draft_response"],
                }
            return {"violations": [], "final_response": state["draft_response"]}

        with patch("agent.query_lifecycle.router_node", return_value={"query_type": "topical"}), \
             patch("agent.query_lifecycle.retriever_node", return_value={"retrieved_chunks": []}), \
             patch("agent.query_lifecycle.synthesiser_node", side_effect=fake_synthesiser), \
             patch("agent.query_lifecycle.supervisor_node", side_effect=fake_supervisor):
            result = run_query("What does the law say?")

        self.assertEqual(result["response"], "Section 1 of Example Act applies.")
        self.assertEqual(result["violations"], [])


if __name__ == "__main__":
    unittest.main()
