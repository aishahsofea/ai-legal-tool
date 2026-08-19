import importlib
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("CHECKPOINTER", "memory")

from agent.nodes import retriever
from agent.retrieval import agent as retrieval_agent
from agent.retrieval import tools as retrieval_tools
from agent.retrieval.agent import _dedupe_chunks
from agent.retrieval.reference_graph import empty_reference_metrics
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, _tools, **_kwargs):
        return self


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


class FollowToolBindingTests(unittest.TestCase):
    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def test_disabled_variant_keeps_exact_merged_tools_prompt_and_schema(self):
        sentinel = object()
        with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": ""}), \
             patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_react_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section"],
        )
        self.assertEqual(kwargs["prompt"], retrieval_agent._SYSTEM)
        self.assertIs(kwargs["state_schema"], retrieval_agent.RetrievalState)
        self.assertNotIn("context_schema", kwargs)

    def test_enabled_variant_adds_only_follow_tool_and_conditional_prompt(self):
        sentinel = object()
        with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": "on"}), \
             patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_react_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section", "follow_references"],
        )
        self.assertIn("explicit statutory-reference intent only", kwargs["prompt"])
        self.assertIs(
            kwargs["state_schema"],
            retrieval_agent.ReferenceRetrievalState,
        )
        self.assertIs(
            kwargs["context_schema"],
            retrieval_agent.RetrievalReferenceContext,
        )

    def test_flag_value_is_part_of_compile_cache_key(self):
        compiled = []

        def fake_create(*_args, **kwargs):
            value = tuple(tool.name for tool in kwargs["tools"])
            compiled.append(value)
            return value

        with patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_react_agent", side_effect=fake_create):
            with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": ""}):
                disabled_first = retrieval_agent.get_retrieval_agent()
            with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": "true"}):
                enabled = retrieval_agent.get_retrieval_agent()
            with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": ""}):
                disabled_second = retrieval_agent.get_retrieval_agent()

        self.assertEqual(disabled_first, ("search_statutes", "lookup_section"))
        self.assertEqual(
            enabled,
            ("search_statutes", "lookup_section", "follow_references"),
        )
        self.assertIs(disabled_first, disabled_second)
        self.assertEqual(len(compiled), 2)


class FollowRetrievalGraphIntegrationTests(unittest.TestCase):
    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    @staticmethod
    def _anchor():
        return {
            "act_number": "265",
            "act_title": "EMPLOYMENT ACT 1955",
            "section_number": "60D",
            "content": "Section 60D refers to section 8 of Act 369.",
            "language": "en",
            "document_id": "act-265-en-sha256-source",
            "extraction_id": "extraction-source",
        }

    @staticmethod
    def _follow_result():
        return {
            "status": "followed",
            "reason": "followed",
            "chunks": [{
                "act_number": "369",
                "act_title": "HOLIDAYS ACT 1951",
                "section_number": "8",
                "content": "Section 8 fixture.",
                "language": "en",
                "document_id": "act-369-en-sha256-target",
                "extraction_id": "extraction-target",
            }],
            "metrics": {
                **empty_reference_metrics(),
                "calls": 1,
                "edges_considered": 1,
                "edges_returned": 1,
                "targets_looked_up": 1,
                "targets_resolved": 1,
                "boundary_targets": 1,
            },
            "edges": [{"edge_id": "edge:1"}],
            "targets": [{
                "provision_id": "act:369/section:8",
                "lookup_status": "resolved",
                "boundary": True,
            }],
        }

    def test_real_react_loop_establishes_anchor_then_follows_once(self):
        model = _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "lookup_section",
                "args": {"section": "60D", "act": "Employment Act"},
                "id": "lookup_1",
                "type": "tool_call",
            }]),
            AIMessage(content="", tool_calls=[{
                "name": "follow_references",
                "args": {
                    "act": "265",
                    "provision": "60D",
                    "direction": "outgoing",
                },
                "id": "follow_1",
                "type": "tool_call",
            }]),
            AIMessage(content="Retrieved the direct published reference."),
        ])
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "true",
            "LANGCHAIN_TRACING_V2": "false",
        }), patch.object(retrieval_agent, "make_llm", return_value=model), \
             patch.object(
                 retrieval_tools,
                 "exact_section_lookup",
                 return_value=[self._anchor()],
             ), patch.object(
                 retrieval_tools,
                 "follow_published_references",
                 return_value=self._follow_result(),
             ) as follow:
            result = retrieval_agent.run_retrieval_agent(
                "What provisions does section 60D of the Employment Act refer to?"
            )

        self.assertEqual(
            result["tools"],
            ["lookup_section", "follow_references"],
        )
        self.assertEqual(
            {(row["act_number"], row["section_number"]) for row in result["chunks"]},
            {("265", "60D"), ("369", "8")},
        )
        self.assertEqual(result["reference_metrics"]["calls"], 1)
        follow.assert_called_once()

    def test_real_react_loop_runtime_gate_blocks_wrong_negative_selection(self):
        model = _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "follow_references",
                "args": {"act": "265", "provision": "60D"},
                "id": "follow_1",
                "type": "tool_call",
            }]),
            AIMessage(content="No traversal."),
        ])
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "true",
            "LANGCHAIN_TRACING_V2": "false",
        }), patch.object(retrieval_agent, "make_llm", return_value=model), \
             patch.object(retrieval_tools, "follow_published_references") as follow:
            result = retrieval_agent.run_retrieval_agent(
                "What does section 60D of the Employment Act say?"
            )

        follow.assert_not_called()
        self.assertEqual(result["reference_metrics"]["skipped"], 1)
        self.assertEqual(
            result["reference_trace"][0]["reason"],
            "intent_not_selective",
        )

    def test_real_react_loop_parallel_duplicates_share_once_guard(self):
        model = _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "lookup_section",
                "args": {"section": "60D", "act": "Employment Act"},
                "id": "lookup_1",
                "type": "tool_call",
            }]),
            AIMessage(content="", tool_calls=[
                {
                    "name": "follow_references",
                    "args": {"act": "265", "provision": "60D"},
                    "id": "follow_1",
                    "type": "tool_call",
                },
                {
                    "name": "follow_references",
                    "args": {"act": "265", "provision": "60D"},
                    "id": "follow_2",
                    "type": "tool_call",
                },
            ]),
            AIMessage(content="Done."),
        ])
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "true",
            "LANGCHAIN_TRACING_V2": "false",
        }), patch.object(retrieval_agent, "make_llm", return_value=model), \
             patch.object(
                 retrieval_tools,
                 "exact_section_lookup",
                 return_value=[self._anchor()],
             ), patch.object(
                 retrieval_tools,
                 "follow_published_references",
                 return_value=self._follow_result(),
             ) as follow:
            result = retrieval_agent.run_retrieval_agent(
                "What provisions does section 60D refer to?"
            )

        follow.assert_called_once()
        self.assertEqual(result["reference_metrics"]["calls"], 2)
        self.assertEqual(result["reference_metrics"]["skipped"], 1)
        self.assertEqual(
            {trace["reason"] for trace in result["reference_trace"]},
            {"followed", "already_followed_this_run"},
        )

    def test_real_disabled_react_loop_preserves_original_result_contract(self):
        model = _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "lookup_section",
                "args": {"section": "60D", "act": "Employment Act"},
                "id": "lookup_1",
                "type": "tool_call",
            }]),
            AIMessage(content="Found the exact section."),
        ])
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "",
            "LANGSMITH_TRACING": "false",
        }), patch.object(retrieval_agent, "make_llm", return_value=model), \
             patch.object(
                 retrieval_tools,
                 "exact_section_lookup",
                 return_value=[self._anchor()],
             ):
            result = retrieval_agent.run_retrieval_agent(
                "What does section 60D of the Employment Act say?"
            )
        self.assertEqual(set(result), {"chunks", "tools"})
        self.assertEqual(result["tools"], ["lookup_section"])
        self.assertEqual(result["chunks"], [self._anchor()])


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
