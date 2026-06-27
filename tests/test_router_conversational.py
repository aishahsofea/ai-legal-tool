import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import router
from agent.nodes.router import _RouterOutput


class RouterConversationalTests(unittest.TestCase):
    def _route(self, query_type: str, response_language: str = "en"):
        result = _RouterOutput(
            query_type=query_type,
            response_language=response_language,
            reasoning="test",
        )
        with patch.object(router, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = result
            return router.router_node({"query": "hi my name is shameel", "history": []})

    def test_greeting_classified_conversational(self):
        state = self._route("conversational")
        self.assertEqual(state["query_type"], "conversational")

    def test_response_language_propagates_for_conversational(self):
        state = self._route("conversational", response_language="bm")
        self.assertEqual(state["query_type"], "conversational")
        self.assertEqual(state["response_language"], "bm")

    def test_escalation_precheck_beats_conversational(self):
        # "my client" trips the escalation regex before any LLM call, even if the
        # message also looks like a greeting — escalation precedence is intact.
        state = router.router_node({
            "query": "hi! my client has been charged, am i liable?",
            "history": [],
        })
        self.assertEqual(state["query_type"], "escalate")


if __name__ == "__main__":
    unittest.main()
