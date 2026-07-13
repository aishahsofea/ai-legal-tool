"""Barge-in / cancellation contract for run_query_stream.

Covers the three things a "press Esc" barge-in must guarantee:
  1. cancel_thread() stops an in-flight run and no response event is emitted.
  2. A cancelled (abandoned) turn writes NOTHING to history, and a fresh prompt on
     the same thread records only itself — the pending checkpoint task from the
     aborted turn must not resume or duplicate (the snapshot.next question).
  3. Single active run per thread: starting a new run cancels the prior one.

The async path (graph.astream) drives the ASYNC node twins, so the LLM nodes are
patched via their `a*_node` names in agent.graph.
"""
import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent import query_lifecycle
from agent.graph import build_graph


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "user_id": None}}


def _patch_async_happy_path(stack: ExitStack, asynthesiser) -> None:
    """Topical happy path for the ASYNC (astream) execution: classify topical,
    retrieve nothing, pass every check. synthesiser is supplied by the caller so a
    test can make it block. Sync-only nodes (retriever/citation/supervisor) run
    their sync func in a threadpool during astream, so they are patched by base name."""
    stack.enter_context(patch("agent.graph.arouter_node", side_effect=lambda s: {"query_type": "topical"}))
    stack.enter_context(patch("agent.graph.acontextualize_node", side_effect=lambda s: {"standalone_query": ""}))
    stack.enter_context(patch("agent.graph.agrounding_check_node", side_effect=lambda s: {"violations": []}))
    stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.supervisor_node", side_effect=lambda s: {"violations": [], "final_response": s["draft_response"]}))
    stack.enter_context(patch("agent.graph.asynthesiser_node", side_effect=asynthesiser))


class BargeInTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._saved_graph = query_lifecycle.graph

    async def asyncTearDown(self):
        query_lifecycle.graph = self._saved_graph
        query_lifecycle._active_runs.clear()

    async def _drain(self, thread_id: str, query: str, events: list) -> None:
        async for event in query_lifecycle.run_query_stream(query, thread_id):
            events.append(event)

    async def test_cancel_midturn_emits_no_response_and_cleans_registry(self):
        reached = asyncio.Event()
        release = asyncio.Event()  # never set → synthesiser blocks until cancelled

        async def blocking_synth(state):
            reached.set()
            await release.wait()
            return {"draft_response": "Section 1 of Example Act applies.", "citations": []}

        thread = "barge-1"
        with ExitStack() as stack:
            _patch_async_happy_path(stack, blocking_synth)
            query_lifecycle.set_graph(build_graph(MemorySaver()))

            events: list = []
            consumer = asyncio.create_task(self._drain(thread, "first question", events))
            await asyncio.wait_for(reached.wait(), timeout=5)

            # Barge in.
            self.assertTrue(query_lifecycle.cancel_thread(thread))
            await asyncio.wait_for(consumer, timeout=5)

        # The aborted turn produced no answer and left no registry entry behind.
        self.assertNotIn("response", [e.get("type") for e in events])
        self.assertNotIn(thread, query_lifecycle._active_runs)

    async def test_abandoned_turn_leaves_history_clean_for_next_prompt(self):
        # The crux: cancel mid-synthesiser, then send a NEW prompt on the SAME thread.
        # History must contain ONLY the second turn — the pending checkpoint task from
        # the aborted turn must neither resume nor duplicate.
        checkpointer = MemorySaver()
        thread = "barge-2"
        config = _config(thread)

        reached = asyncio.Event()
        release = asyncio.Event()

        async def blocking_synth(state):
            reached.set()
            await release.wait()
            return {"draft_response": "abandoned", "citations": []}

        with ExitStack() as stack:
            _patch_async_happy_path(stack, blocking_synth)
            query_lifecycle.set_graph(build_graph(checkpointer))
            events: list = []
            consumer = asyncio.create_task(self._drain(thread, "aborted question", events))
            await asyncio.wait_for(reached.wait(), timeout=5)
            query_lifecycle.cancel_thread(thread)
            await asyncio.wait_for(consumer, timeout=5)

        # Turn 2: a normal completing synthesiser on the same thread (same checkpointer).
        async def good_synth(state):
            return {"draft_response": "Section 5 of Example Act applies. This does not constitute legal advice.", "citations": []}

        with ExitStack() as stack:
            _patch_async_happy_path(stack, good_synth)
            graph2 = build_graph(checkpointer)
            query_lifecycle.set_graph(graph2)
            events2: list = []
            await self._drain(thread, "real question", events2)

        self.assertIn("response", [e.get("type") for e in events2])
        history = graph2.get_state(config).values["history"]
        # Exactly one turn — the aborted turn left no trace and did not resume.
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "real question"})
        self.assertEqual(history[1]["role"], "assistant")
        self.assertTrue(history[1]["content"].startswith("Section 5 of Example Act applies."))
        self.assertNotIn("aborted", " ".join(m["content"] for m in history))

    async def test_new_run_supersedes_prior_run_on_same_thread(self):
        # Single-active-run invariant: a second run_query_stream on the same thread
        # cancels the first, so a user who changes their mind never races two runs.
        reached1 = asyncio.Event()
        release = asyncio.Event()

        async def first_synth(state):
            reached1.set()
            await release.wait()
            return {"draft_response": "first", "citations": []}

        thread = "barge-3"
        with ExitStack() as stack:
            _patch_async_happy_path(stack, first_synth)
            query_lifecycle.set_graph(build_graph(MemorySaver()))
            events1: list = []
            first = asyncio.create_task(self._drain(thread, "q1", events1))
            await asyncio.wait_for(reached1.wait(), timeout=5)
            first_task = query_lifecycle._active_runs[thread]

            # A brand-new turn on the same thread must cancel the first.
            release.set()
            events2: list = []
            second = asyncio.create_task(self._drain(thread, "q2", events2))
            await asyncio.wait_for(first, timeout=5)
            self.assertTrue(first_task.cancelled() or first_task.done())
            self.assertNotIn("response", [e.get("type") for e in events1])
            await asyncio.wait_for(second, timeout=5)
            self.assertIn("response", [e.get("type") for e in events2])


if __name__ == "__main__":
    unittest.main()
