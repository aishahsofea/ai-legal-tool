import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agent.retrieval import tools
from agent.retrieval.reference_graph import (
    FollowOnceGuard,
    RetrievalReferenceContext,
    empty_reference_metrics,
)


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


def _runtime(context, *, chunks=None, followed=False, call_id="follow_1"):
    return ToolRuntime(
        state={
            "retrieved_chunks": chunks or [],
            "reference_followed": followed,
        },
        context=context,
        config={},
        stream_writer=lambda _event: None,
        tool_call_id=call_id,
        store=None,
    )


class FollowReferencesToolTests(unittest.TestCase):
    def test_runtime_argument_is_hidden_from_model_schema(self):
        self.assertNotIn("runtime", tools.follow_references.args)
        self.assertEqual(
            set(tools.follow_references.args),
            {
                "act",
                "provision",
                "direction",
                "relationship_kinds",
                "max_edges",
                "document_id",
            },
        )

    def test_negative_intent_never_reaches_graph_adapter(self):
        context = RetrievalReferenceContext(
            follow_allowed=False,
            follow_guard=FollowOnceGuard(),
        )
        runtime = _runtime(context, chunks=[{
            "act_number": "265",
            "section_number": "60D",
            "document_id": "document",
            "extraction_id": "extraction",
        }])
        with patch.object(tools, "follow_published_references") as follow:
            cmd = tools.follow_references.func(
                act="265",
                provision="60D",
                runtime=runtime,
            )
        follow.assert_not_called()
        self.assertTrue(cmd.update["reference_followed"])
        self.assertEqual(
            cmd.update["reference_trace"][0]["reason"],
            "intent_not_selective",
        )
        self.assertEqual(cmd.update["reference_metrics"]["skipped"], 1)

    def test_positive_intent_delegates_anchor_state_and_returns_chunks(self):
        context = RetrievalReferenceContext(
            follow_allowed=True,
            follow_guard=FollowOnceGuard(),
        )
        anchor = {
            "act_number": "265",
            "section_number": "60D",
            "document_id": "document",
            "extraction_id": "extraction",
        }
        target = {
            "act_number": "369",
            "section_number": "8",
            "document_id": "target-document",
            "extraction_id": "target-extraction",
        }
        result = {
            "status": "followed",
            "reason": "followed",
            "chunks": [target],
            "metrics": {**empty_reference_metrics(), "calls": 1, "edges_returned": 1},
            "edges": [{"edge_id": "edge:1"}],
            "targets": [{
                "provision_id": "act:369/section:8",
                "lookup_status": "resolved",
            }],
        }
        with patch.object(tools, "follow_published_references", return_value=result) as follow, \
             patch.object(tools, "_emit") as emit:
            cmd = tools.follow_references.func(
                act="265",
                provision="60D",
                runtime=_runtime(context, chunks=[anchor]),
                direction="both",
                relationship_kinds=["explicit_reference"],
                max_edges=99,
            )
        follow.assert_called_once_with(
            act="265",
            provision="60D",
            retrieved_chunks=[anchor],
            direction="both",
            relationship_kinds=["explicit_reference"],
            max_edges=99,
            document_id=None,
        )
        self.assertEqual(cmd.update["retrieved_chunks"], [target])
        self.assertNotIn("chunks", cmd.update["reference_trace"][0])
        self.assertNotIn("metrics", cmd.update["reference_trace"][0])
        emit.assert_called_once_with(
            "follow_references",
            "Following direct published statutory references",
        )

    def test_parallel_duplicate_calls_execute_only_one_follow_operation(self):
        context = RetrievalReferenceContext(
            follow_allowed=True,
            follow_guard=FollowOnceGuard(),
        )
        result = {
            "status": "followed",
            "reason": "followed",
            "chunks": [],
            "metrics": {**empty_reference_metrics(), "calls": 1},
            "edges": [],
            "targets": [],
        }

        def invoke(index):
            return tools.follow_references.func(
                act="265",
                provision="60D",
                runtime=_runtime(context, call_id=f"follow_{index}"),
                direction="incoming",
            )

        with patch.object(tools, "follow_published_references", return_value=result) as follow:
            with ThreadPoolExecutor(max_workers=2) as executor:
                commands = list(executor.map(invoke, range(2)))

        self.assertEqual(follow.call_count, 1)
        reasons = {
            command.update["reference_trace"][0]["reason"]
            for command in commands
        }
        self.assertEqual(reasons, {"followed", "already_followed_this_run"})

    def test_state_guard_blocks_a_later_call_even_with_fresh_context(self):
        context = RetrievalReferenceContext(
            follow_allowed=True,
            follow_guard=FollowOnceGuard(),
        )
        with patch.object(tools, "follow_published_references") as follow:
            cmd = tools.follow_references.func(
                act="265",
                provision="60D",
                runtime=_runtime(context, followed=True),
            )
        follow.assert_not_called()
        self.assertEqual(
            cmd.update["reference_trace"][0]["reason"],
            "already_followed_this_run",
        )


if __name__ == "__main__":
    unittest.main()
