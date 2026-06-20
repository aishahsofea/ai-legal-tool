"""contextualize_node — resolves an elliptical follow-up into a self-contained
Standalone Query for retrieval, using disclaimer-free history.

These tests cover the contract only (gate, fail-open, token preservation, no-call),
not the LLM's rewrite quality (eval territory).
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import contextualize
from agent.nodes.contextualize import _ContextualizeOutput


def _history(*pairs):
    msgs = []
    for user, assistant in pairs:
        msgs.append({"role": "user", "content": user})
        msgs.append({"role": "assistant", "content": assistant})
    return msgs


class ContextualizeGateTests(unittest.TestCase):
    def test_empty_history_skips_llm_and_returns_empty(self):
        with patch.object(contextualize, "_structured_llm") as mock_llm:
            result = contextualize.contextualize_node({"query": "What is Section 5?", "history": []})
        mock_llm.invoke.assert_not_called()
        self.assertEqual(result, {"standalone_query": ""})

    def test_missing_history_key_skips_llm(self):
        with patch.object(contextualize, "_structured_llm") as mock_llm:
            result = contextualize.contextualize_node({"query": "What is Section 5?"})
        mock_llm.invoke.assert_not_called()
        self.assertEqual(result, {"standalone_query": ""})


class ContextualizeRewriteTests(unittest.TestCase):
    def _run(self, standalone: str, query: str = "what about criminal cases?"):
        with patch.object(contextualize, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = _ContextualizeOutput(standalone_query=standalone)
            return contextualize.contextualize_node({
                "query": query,
                "history": _history(("What does Section 5 of the PDPA say?", "Section 5 governs consent.")),
            })

    def test_follow_up_resolved_into_standalone_query(self):
        result = self._run("Does the PDPA apply to criminal cases?")
        self.assertEqual(result["standalone_query"], "Does the PDPA apply to criminal cases?")

    def test_section_and_act_tokens_survive_verbatim(self):
        result = self._run("What does Section 90A of the Evidence Act 1950 cover?")
        self.assertIn("Section 90A", result["standalone_query"])
        self.assertIn("Evidence Act 1950", result["standalone_query"])

    def test_self_contained_query_returned_unchanged(self):
        result = self._run("What does Section 5 of the PDPA say?")
        self.assertEqual(result["standalone_query"], "What does Section 5 of the PDPA say?")


class ContextualizeFailOpenTests(unittest.TestCase):
    def test_llm_exception_fails_open_to_empty(self):
        with patch.object(contextualize, "_structured_llm") as mock_llm:
            mock_llm.invoke.side_effect = RuntimeError("LLM down")
            result = contextualize.contextualize_node({
                "query": "what about criminal cases?",
                "history": _history(("What does Section 5 say?", "Section 5 governs consent.")),
            })
        self.assertEqual(result, {"standalone_query": ""})

    def test_empty_llm_output_fails_open_to_empty(self):
        with patch.object(contextualize, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = _ContextualizeOutput(standalone_query="   ")
            result = contextualize.contextualize_node({
                "query": "what about criminal cases?",
                "history": _history(("What does Section 5 say?", "Section 5 governs consent.")),
            })
        self.assertEqual(result, {"standalone_query": ""})


if __name__ == "__main__":
    unittest.main()
