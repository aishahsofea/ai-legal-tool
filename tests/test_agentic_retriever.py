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
from langgraph.errors import GraphRecursionError


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

    def test_threads_commentary_onto_the_state_update(self):
        rows = [{"act_number": "709", "section_number": "5"}]
        notes = [{"url": "https://skrine.com/x", "title": "t", "publisher": "skrine.com",
                  "published_date": "", "retrieved_at": "", "snippet": ""}]
        out = {"chunks": rows, "tools": ["search_statutes"], "commentary": notes}
        with patch("agent.retrieval.agent.run_retrieval_agent", return_value=out):
            result = retriever.agentic_retriever_node({
                "query": "data privacy for employers",
                "query_type": "topical",
            })
        self.assertEqual(result["commentary"], notes)

    def test_preserves_commentary_even_when_falling_back_to_deterministic(self):
        det_rows = [{"act_number": "56", "section_number": "90A"}]
        notes = [{"url": "https://skrine.com/x", "title": "t", "publisher": "skrine.com",
                  "published_date": "", "retrieved_at": "", "snippet": ""}]
        out = {"chunks": [], "tools": [], "commentary": notes}
        with patch("agent.retrieval.agent.run_retrieval_agent", return_value=out), \
             patch.object(retriever, "semantic_search", return_value=det_rows):
            result = retriever.agentic_retriever_node({
                "query": "q", "query_type": "topical",
            })
        self.assertEqual(result["retrieved_chunks"], det_rows)
        self.assertEqual(result["commentary"], notes)


class ToolTraceChannelTests(unittest.TestCase):
    """Error and empty-result paths must land in the trace too. Each tool writes
    its own name, so an omission is silent — nothing else would catch it."""

    @staticmethod
    def _invoke(tool, **kwargs):
        return tool.invoke(
            {"name": tool.name, "args": kwargs, "id": "call_1", "type": "tool_call"},
        )

    def test_search_statutes_traces_on_hit(self):
        rows = [{"act_number": "56", "section_number": "90A"}]
        with patch.object(retrieval_tools, "semantic_search", return_value=rows):
            command = self._invoke(retrieval_tools.search_statutes, query="privacy")
        self.assertEqual(command.update["tool_trace"], ["search_statutes"])
        self.assertEqual(command.update["retrieved_chunks"], rows)

    def test_search_statutes_traces_when_search_raises(self):
        with patch.object(retrieval_tools, "semantic_search", side_effect=RuntimeError("boom")):
            command = self._invoke(retrieval_tools.search_statutes, query="privacy")
        self.assertEqual(command.update["tool_trace"], ["search_statutes"])
        self.assertEqual(command.update["retrieved_chunks"], [])

    def test_lookup_section_traces_on_hit(self):
        rows = [{"act_number": "265", "section_number": "60D"}]
        with patch.object(retrieval_tools, "exact_section_lookup", return_value=rows):
            command = self._invoke(
                retrieval_tools.lookup_section, section="60D", act="Employment Act",
            )
        self.assertEqual(command.update["tool_trace"], ["lookup_section"])
        self.assertEqual(command.update["retrieved_chunks"], rows)

    def test_lookup_section_traces_on_no_match(self):
        with patch.object(retrieval_tools, "exact_section_lookup", return_value=[]):
            command = self._invoke(
                retrieval_tools.lookup_section, section="999Z", act="Employment Act",
            )
        self.assertEqual(command.update["tool_trace"], ["lookup_section"])
        self.assertEqual(command.update["retrieved_chunks"], [])

    def test_lookup_section_traces_when_lookup_raises(self):
        with patch.object(retrieval_tools, "exact_section_lookup", side_effect=RuntimeError("boom")):
            command = self._invoke(
                retrieval_tools.lookup_section, section="60D", act="Employment Act",
            )
        self.assertEqual(command.update["tool_trace"], ["lookup_section"])
        self.assertEqual(command.update["retrieved_chunks"], [])


class FollowToolBindingTests(unittest.TestCase):
    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def test_disabled_variant_keeps_exact_merged_tools_prompt_and_schema(self):
        sentinel = object()
        with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": ""}), \
             patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section"],
        )
        self.assertEqual(kwargs["system_prompt"], retrieval_agent._SYSTEM)
        self.assertIs(kwargs["state_schema"], retrieval_agent.RetrievalState)
        self.assertNotIn("context_schema", kwargs)

    def test_enabled_variant_adds_only_follow_tool_and_conditional_prompt(self):
        sentinel = object()
        with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": "on"}), \
             patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section", "follow_references"],
        )
        self.assertIn("explicit statutory-reference intent only", kwargs["system_prompt"])
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
             patch.object(retrieval_agent, "create_agent", side_effect=fake_create):
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


class CommentaryToolBindingTests(unittest.TestCase):
    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def test_enabled_variant_adds_only_commentary_tool_and_conditional_prompt(self):
        sentinel = object()
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "",
            "WEB_COMMENTARY_ENABLED": "on",
        }), patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section", "search_commentary"],
        )
        self.assertIn("allowlist of trusted Malaysian legal-commentary", kwargs["system_prompt"])
        # commentary_enabled alone must not switch the state schema or add a
        # context_schema — only follow_enabled does that.
        self.assertIs(kwargs["state_schema"], retrieval_agent.RetrievalState)
        self.assertNotIn("context_schema", kwargs)

    def test_both_flags_on_binds_all_tools_on_the_reference_schema(self):
        sentinel = object()
        with patch.dict(os.environ, {
            "FOLLOW_REFERENCES_ENABLED": "on",
            "WEB_COMMENTARY_ENABLED": "on",
        }), patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_agent", return_value=sentinel) as create:
            self.assertIs(retrieval_agent.get_retrieval_agent(), sentinel)

        kwargs = create.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in kwargs["tools"]],
            ["search_statutes", "lookup_section", "follow_references", "search_commentary"],
        )
        self.assertIn("explicit statutory-reference intent only", kwargs["system_prompt"])
        self.assertIn("allowlist of trusted Malaysian legal-commentary", kwargs["system_prompt"])
        self.assertIs(kwargs["state_schema"], retrieval_agent.ReferenceRetrievalState)
        self.assertIs(kwargs["context_schema"], retrieval_agent.RetrievalReferenceContext)

    def test_all_four_flag_combinations_compile_independently(self):
        """Regression guard for the lru_cache sizing: two independent flags make
        four tool-and-prompt combinations, and a cache sized for fewer would
        silently reuse the wrong compiled agent for whichever combo evicted."""
        compiled = []

        def fake_create(*_args, **kwargs):
            value = tuple(tool.name for tool in kwargs["tools"])
            compiled.append(value)
            return value

        combos = [("", ""), ("true", ""), ("", "true"), ("true", "true")]
        with patch.object(retrieval_agent, "make_llm", return_value=object()), \
             patch.object(retrieval_agent, "create_agent", side_effect=fake_create):
            results = []
            for follow_value, commentary_value in combos:
                with patch.dict(os.environ, {
                    "FOLLOW_REFERENCES_ENABLED": follow_value,
                    "WEB_COMMENTARY_ENABLED": commentary_value,
                }):
                    results.append(retrieval_agent.get_retrieval_agent())

            # Re-requesting the first combo must hit the cache, not recompile.
            with patch.dict(os.environ, {"FOLLOW_REFERENCES_ENABLED": "", "WEB_COMMENTARY_ENABLED": ""}):
                results.append(retrieval_agent.get_retrieval_agent())

        self.assertEqual(len(compiled), 4)
        self.assertEqual(results[0], ("search_statutes", "lookup_section"))
        self.assertEqual(results[1], ("search_statutes", "lookup_section", "follow_references"))
        self.assertEqual(results[2], ("search_statutes", "lookup_section", "search_commentary"))
        self.assertEqual(
            results[3],
            ("search_statutes", "lookup_section", "follow_references", "search_commentary"),
        )
        self.assertEqual(results[4], results[0])


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


class CommentaryRetrievalGraphIntegrationTests(unittest.TestCase):
    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def test_real_react_loop_calls_commentary_tool_and_populates_channel(self):
        anchor = {
            "act_number": "265",
            "act_title": "EMPLOYMENT ACT 1955",
            "section_number": "60D",
            "content": "Section 60D text.",
            "language": "en",
            "document_id": "act-265-en-sha256-source",
            "extraction_id": "extraction-source",
        }
        commentary_result = {
            "status": "ok",
            "reason": "",
            "results": [{
                "url": "https://skrine.com/insights/60d",
                "title": "What section 60D means in practice",
                "domain": "skrine.com",
                "published_date": "2024-03-01",
                "retrieved_at": "2024-03-02T00:00:00+00:00",
                "snippet": "Practitioner note.",
            }],
            "metrics": {},
        }
        model = _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "lookup_section",
                "args": {"section": "60D", "act": "Employment Act"},
                "id": "lookup_1",
                "type": "tool_call",
            }]),
            AIMessage(content="", tool_calls=[{
                "name": "search_commentary",
                "args": {"query": "section 60D practical effect"},
                "id": "commentary_1",
                "type": "tool_call",
            }]),
            AIMessage(content="Found the section plus background."),
        ])
        with patch.dict(os.environ, {
            "WEB_COMMENTARY_ENABLED": "true",
            "FOLLOW_REFERENCES_ENABLED": "",
            "LANGCHAIN_TRACING_V2": "false",
        }), patch.object(retrieval_agent, "make_llm", return_value=model), \
             patch.object(retrieval_tools, "exact_section_lookup", return_value=[anchor]), \
             patch.object(retrieval_tools, "search_web", return_value=commentary_result) as search_web:
            result = retrieval_agent.run_retrieval_agent(
                "What does section 60D of the Employment Act say, and how do firms advise on it?"
            )

        search_web.assert_called_once()
        self.assertEqual(result["tools"], ["lookup_section", "search_commentary"])
        self.assertEqual([row["act_number"] for row in result["chunks"]], ["265"])
        self.assertEqual(
            result["commentary"],
            [{
                "url": "https://skrine.com/insights/60d",
                "title": "What section 60D means in practice",
                "publisher": "skrine.com",
                "published_date": "2024-03-01",
                "retrieved_at": "2024-03-02T00:00:00+00:00",
                "snippet": "Practitioner note.",
            }],
        )


class ModelCallBudgetTests(unittest.TestCase):
    """A loop that never decides it is done has to be stopped by the code, and it
    has to stop holding what it found. #133: it raised instead, and the fail-open
    then discarded every section the agent had already retrieved."""

    def setUp(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    def tearDown(self):
        retrieval_agent._build_retrieval_agent.cache_clear()

    @staticmethod
    def _row():
        return {
            "act_number": "265",
            "act_title": "EMPLOYMENT ACT 1955",
            "section_number": "19",
            "content": "Wages payable within seven days.",
            "language": "en",
            "document_id": "act-265-en-sha256-source",
            "extraction_id": "extraction-source",
        }

    @staticmethod
    def _endless_searcher():
        # FakeMessagesListChatModel cycles its responses, so a model that only ever
        # asks for another search never stops on its own — the runaway seen on
        # multi-section-wages-hours-1, where it reformulated past 15 calls hunting a
        # penalty section the corpus does not hold.
        return _ToolCallingFakeModel(responses=[
            AIMessage(content="", tool_calls=[{
                "name": "search_statutes",
                "args": {"query": f"employment act penalty attempt {i}"},
                "id": f"search_{i}",
                "type": "tool_call",
            }])
            for i in range(4)
        ])

    def test_model_call_budget_ends_the_loop_without_raising(self):
        budget = 3
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}), \
             patch.object(retrieval_agent, "MAX_MODEL_CALLS", budget), \
             patch.object(retrieval_agent, "RECURSION_LIMIT", 4 * budget + 2), \
             patch.object(retrieval_agent, "make_llm", return_value=self._endless_searcher()), \
             patch.object(retrieval_tools, "semantic_search", return_value=[self._row()]):
            # No warning: the budget must end the run, not the recursion backstop.
            with self.assertNoLogs("agent.retrieval.agent", level="WARNING"):
                result = retrieval_agent.run_retrieval_agent("wages and hours remedies")

        self.assertEqual(result["tools"], ["search_statutes"] * budget)
        self.assertEqual(result["chunks"], [self._row()])

    def test_recursion_backstop_keeps_what_the_agent_already_found(self):
        """Lowering RETRIEVAL_RECURSION_LIMIT below the call budget is an operator
        mistake, not a reason to hand the caller nothing."""
        partial = {"retrieved_chunks": [self._row()], "tool_trace": ["search_statutes"]}

        class _StallingAgent:
            def stream(self, _input, _config, **_kwargs):
                yield "values", partial
                raise GraphRecursionError("Recursion limit of 2 reached")

        with patch.object(retrieval_agent, "_build_retrieval_agent", return_value=_StallingAgent()):
            with self.assertLogs("agent.retrieval.agent", level="WARNING"):
                result = retrieval_agent.run_retrieval_agent("wages and hours remedies")

        self.assertEqual(result["chunks"], [self._row()])
        self.assertEqual(result["tools"], ["search_statutes"])

    def test_recursion_limit_leaves_room_for_the_budget_to_fire_first(self):
        # Each model round costs four super-steps once the middleware's before_model
        # and after_model nodes are in the graph.
        self.assertGreaterEqual(
            retrieval_agent.RECURSION_LIMIT,
            4 * retrieval_agent.MAX_MODEL_CALLS + 2,
        )


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
