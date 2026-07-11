import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("CHECKPOINTER", "memory")

from agent.nodes import retriever
from agent.retrieval.agent import _dedupe_chunks


class DedupeReducerTests(unittest.TestCase):
    def test_accumulates_and_dedupes_case_insensitively(self):
        left = [{"act_number": "56", "section_number": "90A", "language": "en"}]
        right = [
            {"act_number": "56", "section_number": "90a", "language": "en"},  # dup
            {"act_number": "709", "section_number": "5", "language": "en"},
        ]
        merged = _dedupe_chunks(left, right)
        self.assertEqual([(c["act_number"], c["section_number"]) for c in merged],
                         [("56", "90A"), ("709", "5")])

    def test_handles_none(self):
        self.assertEqual(_dedupe_chunks(None, None), [])


class AgenticRetrieverNodeTests(unittest.TestCase):
    def test_returns_agent_chunks_and_tool_trace_on_success(self):
        rows = [{"act_number": "709", "section_number": "5"}]
        out = {"chunks": rows, "tools": ["search_statutes"]}
        with patch("agent.retrieval.agent.run_retrieval_agent", return_value=out) as run:
            result = retriever.agentic_retriever_node({
                "query": "data privacy for employers",
                "query_type": "topical",
            })
        run.assert_called_once_with("data privacy for employers", "", None)
        self.assertEqual(result["retrieved_chunks"], rows)
        self.assertEqual(result["tool_trace"], ["search_statutes"])

    def test_forwards_standalone_query_and_feedback(self):
        out = {"chunks": [{"a": 1}], "tools": ["lookup_section"]}
        with patch("agent.retrieval.agent.run_retrieval_agent", return_value=out) as run:
            retriever.agentic_retriever_node({
                "query": "what about it?",
                "standalone_query": "penalty under the Employment Act",
                "retrieval_feedback": "previous search missed s.60",
                "query_type": "topical",
            })
        run.assert_called_once_with("penalty under the Employment Act", "previous search missed s.60", None)

    def test_fails_open_to_deterministic_on_exception(self):
        det_rows = [{"act_number": "56", "section_number": "90A"}]
        with patch("agent.retrieval.agent.run_retrieval_agent", side_effect=RuntimeError("boom")), \
             patch.object(retriever, "semantic_search", return_value=det_rows):
            result = retriever.agentic_retriever_node({
                "query": "q", "query_type": "topical",
            })
        self.assertEqual(result["retrieved_chunks"], det_rows)

    def test_fails_open_to_deterministic_on_empty(self):
        det_rows = [{"act_number": "56", "section_number": "90A"}]
        with patch("agent.retrieval.agent.run_retrieval_agent", return_value={"chunks": [], "tools": []}), \
             patch.object(retriever, "semantic_search", return_value=det_rows):
            result = retriever.agentic_retriever_node({
                "query": "q", "query_type": "topical",
            })
        self.assertEqual(result["retrieved_chunks"], det_rows)


class FlagDispatchTests(unittest.TestCase):
    def test_flag_off_uses_deterministic(self):
        import agent.graph as graph_module
        with patch.dict(os.environ, {"AGENTIC_RETRIEVAL": ""}):
            self.assertIs(graph_module._select_retriever_node(), graph_module.retriever_node)

    def test_flag_on_uses_agentic(self):
        import agent.graph as graph_module
        with patch.dict(os.environ, {"AGENTIC_RETRIEVAL": "1"}):
            self.assertIs(graph_module._select_retriever_node(), graph_module.agentic_retriever_node)


if __name__ == "__main__":
    unittest.main()
