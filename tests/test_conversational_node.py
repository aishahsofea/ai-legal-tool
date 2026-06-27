import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import conversational
from agent.query_policy import CONVERSATIONAL_FALLBACK_RESPONSE


class ConversationalNodeTests(unittest.TestCase):
    def test_returns_warm_reply_with_no_citations_or_disclaimer(self):
        reply = "Hi Shameel! Ask me about any Malaysian Act and I'll look it up."
        with patch.object(conversational, "_llm") as mock_llm:
            mock_llm.invoke.return_value = Mock(content=reply)
            result = conversational.conversational_node(
                {"query": "hi my name is shameel", "history": [], "response_language": "en"}
            )

        # Asserts structure, not exact text — the node is non-deterministic at temp 0.7.
        self.assertTrue(result["final_response"])
        self.assertEqual(result["final_response"], result["draft_response"])
        # No citations are produced; start_turn already reset them to empty.
        self.assertNotIn("citations", result)
        # No appended disclaimer suffix.
        self.assertNotIn("does not constitute legal advice", result["final_response"])

    def test_fails_closed_to_static_constant_on_llm_exception(self):
        with patch.object(conversational, "_llm") as mock_llm:
            mock_llm.invoke.side_effect = RuntimeError("boom")
            result = conversational.conversational_node(
                {"query": "hi", "history": [], "response_language": "en"}
            )

        self.assertEqual(result["final_response"], CONVERSATIONAL_FALLBACK_RESPONSE)
        self.assertEqual(result["draft_response"], CONVERSATIONAL_FALLBACK_RESPONSE)

    def test_fails_closed_on_empty_llm_output(self):
        with patch.object(conversational, "_llm") as mock_llm:
            mock_llm.invoke.return_value = Mock(content="   ")
            result = conversational.conversational_node(
                {"query": "hi", "history": [], "response_language": "en"}
            )

        self.assertEqual(result["final_response"], CONVERSATIONAL_FALLBACK_RESPONSE)


if __name__ == "__main__":
    unittest.main()
