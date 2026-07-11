import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from agent.retrieval import tools


def _invoke(tool, args: dict) -> Command:
    # Tools with an InjectedToolCallId must be invoked via a tool_call dict so the
    # framework supplies the id the way the ReAct loop does at runtime.
    return tool.invoke({"type": "tool_call", "id": "call_1", "name": tool.name, "args": args})


class SearchStatutesToolTests(unittest.TestCase):
    def test_returns_command_updating_retrieved_chunks(self):
        rows = [{"act_number": "709", "section_number": "5"}]
        with patch.object(tools, "semantic_search", return_value=rows) as sem:
            cmd = _invoke(tools.search_statutes, {"query": "data privacy"})

        sem.assert_called_once_with("data privacy", top_k=8, act_number=None, language=None)
        self.assertIsInstance(cmd, Command)
        self.assertEqual(cmd.update["retrieved_chunks"], rows)
        msg = cmd.update["messages"][0]
        self.assertIsInstance(msg, ToolMessage)
        self.assertIn("Found 1 section", msg.content)

    def test_passes_optional_filters_through(self):
        with patch.object(tools, "semantic_search", return_value=[]) as sem:
            _invoke(tools.search_statutes, {"query": "q", "top_k": 3, "act": "56", "language": "en"})
        sem.assert_called_once_with("q", top_k=3, act_number="56", language="en")

    def test_db_error_fails_open_with_message_not_raise(self):
        with patch.object(tools, "semantic_search", side_effect=RuntimeError("db down")):
            cmd = _invoke(tools.search_statutes, {"query": "q"})
        self.assertEqual(cmd.update["retrieved_chunks"], [])
        self.assertIn("error", cmd.update["messages"][0].content.lower())


class LookupSectionToolTests(unittest.TestCase):
    def test_resolves_alias_act_and_returns_rows(self):
        rows = [{"act_number": "56", "section_number": "90A"}]
        with patch.object(tools, "exact_section_lookup", return_value=rows) as exact:
            cmd = _invoke(tools.lookup_section, {"section": "90A", "act": "Evidence Act"})
        exact.assert_called_once_with("90A", act_number="56", act_title="EVIDENCE ACT 1950")
        self.assertEqual(cmd.update["retrieved_chunks"], rows)

    def test_bare_act_number_passes_through(self):
        with patch.object(tools, "exact_section_lookup", return_value=[]) as exact:
            _invoke(tools.lookup_section, {"section": "90A", "act": "56"})
        exact.assert_called_once_with("90A", act_number="56", act_title=None)

    def test_no_match_reports_fallback_message(self):
        with patch.object(tools, "exact_section_lookup", return_value=[]):
            cmd = _invoke(tools.lookup_section, {"section": "999", "act": "Evidence Act"})
        self.assertEqual(cmd.update["retrieved_chunks"], [])
        self.assertIn("search_statutes", cmd.update["messages"][0].content)


if __name__ == "__main__":
    unittest.main()
