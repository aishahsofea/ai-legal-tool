"""HITL clarification interrupt contract (ADR 0015).

Covers the graph-initiated pause that ADR 0014 (barge-in) explicitly deferred:
  1. router emits query_type="clarify" + a question on an un-actionable query.
  2. clarify_node MERGES the original query with the user's answer (option C) so the
     resumed turn retrieves on the full intent, not the bare answer.
  3. The graph pauses at clarify (__interrupt__) and, on Command(resume=...), runs to
     completion — recording exactly ONE merged turn in history.
  4. The `clarified` guard blocks a second pause in the same turn.
  5. run_query_stream surfaces an `interrupt` event (no response) and resumes cleanly.
  6. The sync eval path fails safe on an interrupt instead of crashing.
"""
import asyncio
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent import query_lifecycle
from agent.graph import build_graph
from agent.nodes import router
from agent.nodes.clarify import clarify_node
from agent.nodes.router import _RouterOutput

AMBIGUOUS = "what does section 5 say?"
ANSWER = "the Contracts Act 1950"
MERGED = f"{AMBIGUOUS} (clarified: {ANSWER})"


class _FakeRouter:
    """Clarify on the first call, then a legal type on the post-resume re-classify."""

    def __init__(self):
        self.calls = 0

    def __call__(self, state):
        self.calls += 1
        if self.calls == 1:
            return {"query_type": "clarify", "response_language": "en",
                    "clarifying_question": "Which Act's section 5 do you mean?"}
        return {"query_type": "statute_lookup", "response_language": "en"}


class RouterClarifyUnitTests(unittest.TestCase):
    def test_router_emits_clarify_with_question(self):
        result = _RouterOutput(
            query_type="clarify",
            response_language="en",
            clarifying_question="Which Act's section 5 do you mean?",
            reasoning="test",
        )
        with patch.object(router, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = result
            state = router.router_node({"query": AMBIGUOUS, "history": []})
        self.assertEqual(state["query_type"], "clarify")
        self.assertEqual(state["clarifying_question"], "Which Act's section 5 do you mean?")

    def test_router_drops_stray_question_on_non_clarify(self):
        # A model that populates clarifying_question on a non-clarify type must not leak it.
        result = _RouterOutput(
            query_type="statute_lookup",
            response_language="en",
            clarifying_question="stray",
            reasoning="test",
        )
        with patch.object(router, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = result
            state = router.router_node({"query": AMBIGUOUS, "history": []})
        self.assertNotIn("clarifying_question", state)


class ClarifyNodeUnitTests(unittest.TestCase):
    def test_merges_original_and_answer(self):
        # interrupt() returns the resume value; patch it to simulate the user's answer.
        with patch("agent.nodes.clarify.interrupt", return_value=ANSWER):
            out = clarify_node({"query": AMBIGUOUS, "clarifying_question": "Which Act?"})
        self.assertEqual(out["query"], MERGED)
        self.assertTrue(out["clarified"])
        self.assertEqual(out["query_type"], "")
        self.assertEqual(out["clarifying_question"], "")

    def test_empty_answer_keeps_original_query(self):
        with patch("agent.nodes.clarify.interrupt", return_value=""):
            out = clarify_node({"query": AMBIGUOUS, "clarifying_question": "Which Act?"})
        self.assertEqual(out["query"], AMBIGUOUS)


def _patch_sync_happy_path(stack: ExitStack, fake_router, seen: dict) -> None:
    """Legal happy path for the SYNC (invoke) execution used by the graph tests."""
    stack.enter_context(patch("agent.graph.router_node", side_effect=fake_router))
    stack.enter_context(patch("agent.graph.contextualize_node", side_effect=lambda s: {"standalone_query": ""}))

    def _retriever(state):
        seen["retriever_query"] = state["query"]
        return {"retrieved_chunks": []}

    def _synth(state):
        return {"draft_response": "Section 5 of the Contracts Act 1950 provides X. This does not constitute legal advice.", "citations": []}

    stack.enter_context(patch("agent.graph.retriever_node", side_effect=_retriever))
    stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=_synth))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.grounding_check_node", side_effect=lambda s: {"violations": []}))
    stack.enter_context(patch("agent.graph.supervisor_node", side_effect=lambda s: {"violations": [], "final_response": s["draft_response"]}))


class GraphInterruptResumeTests(unittest.TestCase):
    def test_pause_then_resume_records_single_merged_turn(self):
        checkpointer = MemorySaver()
        config = {"configurable": {"thread_id": "clarify-1", "user_id": None}}
        seen: dict = {}
        with ExitStack() as stack:
            _patch_sync_happy_path(stack, _FakeRouter(), seen)
            app = build_graph(checkpointer)

            paused = app.invoke({"query": AMBIGUOUS}, config)
            # Paused at clarify: an interrupt is surfaced and no answer was produced.
            self.assertIn("__interrupt__", paused)
            self.assertNotIn("retriever_query", seen)  # retrieval has not run yet

            resumed = app.invoke(Command(resume=ANSWER), config)

        # Retrieval saw the MERGED query (option C), not the bare answer.
        self.assertEqual(seen["retriever_query"], MERGED)
        self.assertTrue(resumed["final_response"].startswith("Section 5 of the Contracts Act 1950"))

        # History holds exactly one turn, and its user content is the merged query.
        history = app.get_state(config).values["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": MERGED})
        self.assertEqual(history[1]["role"], "assistant")

    def test_clarified_guard_blocks_second_pause(self):
        # A router that ALWAYS returns clarify must still pause only once: after the
        # first resume, `clarified` is set and the branch falls through to the legal path.
        checkpointer = MemorySaver()
        config = {"configurable": {"thread_id": "clarify-2", "user_id": None}}
        seen: dict = {}

        def always_clarify(state):
            return {"query_type": "clarify", "response_language": "en",
                    "clarifying_question": "Which Act?"}

        with ExitStack() as stack:
            _patch_sync_happy_path(stack, always_clarify, seen)
            app = build_graph(checkpointer)
            paused = app.invoke({"query": AMBIGUOUS}, config)
            self.assertIn("__interrupt__", paused)
            resumed = app.invoke(Command(resume=ANSWER), config)

        # No second interrupt — the turn completed through retrieval to a response.
        self.assertNotIn("__interrupt__", resumed)
        self.assertIn("retriever_query", seen)


def _patch_async_happy_path(stack: ExitStack, fake_router) -> None:
    """Async (astream) twin of the happy path. clarify_node has no async twin, so it
    runs in a threadpool during astream — interrupt() still fires there."""
    stack.enter_context(patch("agent.graph.arouter_node", side_effect=fake_router))
    stack.enter_context(patch("agent.graph.acontextualize_node", side_effect=lambda s: {"standalone_query": ""}))
    stack.enter_context(patch("agent.graph.agrounding_check_node", side_effect=lambda s: {"violations": []}))
    stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
    stack.enter_context(patch("agent.graph.asynthesiser_node", side_effect=lambda s: {"draft_response": "Section 5 answer. This does not constitute legal advice.", "citations": []}))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.supervisor_node", side_effect=lambda s: {"violations": [], "final_response": s["draft_response"]}))


class StreamInterruptResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._saved_graph = query_lifecycle.graph

    async def asyncTearDown(self):
        query_lifecycle.graph = self._saved_graph
        query_lifecycle._active_runs.clear()

    async def _drain(self, thread_id, query=None, *, resume=None):
        events: list = []
        async for event in query_lifecycle.run_query_stream(query, thread_id, resume=resume):
            events.append(event)
        return events

    async def test_stream_emits_interrupt_then_resumes_to_response(self):
        thread = "clarify-stream-1"
        with ExitStack() as stack:
            _patch_async_happy_path(stack, _FakeRouter())
            query_lifecycle.set_graph(build_graph(MemorySaver()))

            paused = await self._drain(thread, AMBIGUOUS)
            types = [e.get("type") for e in paused]
            self.assertIn("interrupt", types)
            self.assertNotIn("response", types)
            interrupt_evt = next(e for e in paused if e["type"] == "interrupt")
            self.assertEqual(interrupt_evt["question"], "Which Act's section 5 do you mean?")
            # The paused run left the registry (astream ended cleanly at the interrupt).
            self.assertNotIn(thread, query_lifecycle._active_runs)

            resumed = await self._drain(thread, resume=ANSWER)
            self.assertIn("response", [e.get("type") for e in resumed])


class SyncEvalGuardTests(unittest.TestCase):
    def setUp(self):
        self._saved_graph = query_lifecycle.graph

    def tearDown(self):
        query_lifecycle.graph = self._saved_graph

    def test_run_query_fails_safe_on_interrupt(self):
        with ExitStack() as stack:
            _patch_sync_happy_path(stack, _FakeRouter(), {})
            query_lifecycle.set_graph(build_graph(MemorySaver()))
            result = query_lifecycle.run_query(AMBIGUOUS, "eval-clarify-1")
        self.assertEqual(result["query_type"], "clarify")
        self.assertEqual(result["response"], "Which Act's section 5 do you mean?")


if __name__ == "__main__":
    unittest.main()
