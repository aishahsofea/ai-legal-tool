import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from agent.nodes import router
from agent.nodes.router import _RouterOutput


class RouterLanguageTests(unittest.TestCase):
    def _invoke_with_language(self, response_language: str, query_type: str = "statute_lookup"):
        result = _RouterOutput(
            query_type=query_type,
            response_language=response_language,
            reasoning="test",
        )
        with patch.object(router, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = result
            return router.router_node({"query": "test query", "history": []})

    def test_english_query_returns_en(self):
        state = self._invoke_with_language("en")
        self.assertEqual(state["response_language"], "en")

    def test_bm_query_returns_bm(self):
        state = self._invoke_with_language("bm")
        self.assertEqual(state["response_language"], "bm")

    def test_mixed_query_returns_mixed(self):
        state = self._invoke_with_language("mixed")
        self.assertEqual(state["response_language"], "mixed")

    def test_escalation_always_returns_en(self):
        state = router.router_node({
            "query": "my client has been charged with theft, am i liable?",
            "history": [],
        })
        self.assertEqual(state["query_type"], "escalate")
        self.assertEqual(state["response_language"], "en")

    def test_response_language_propagated_alongside_query_type(self):
        state = self._invoke_with_language("bm", query_type="topical")
        self.assertEqual(state["query_type"], "topical")
        self.assertEqual(state["response_language"], "bm")


if __name__ == "__main__":
    unittest.main()
