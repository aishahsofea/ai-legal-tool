"""Checkpointer behaviour tests (MemorySaver backend).

These verify the server-side conversation-memory contract introduced with the
LangGraph checkpointer:
  1. per-turn reset   — turn N does not inherit turn N-1's per-query fields
  2. accumulation     — history grows across turns and nodes see prior turns only
  3. thread isolation — distinct thread_ids never see each other's history
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _enter_passthrough_nodes(stack: ExitStack) -> None:
    """A minimal happy-path stack: classify topical, retrieve nothing, pass every
    policy check. No retries, no escalation. (synthesiser/supervisor are patched
    per-test so the test controls draft content.)"""
    stack.enter_context(patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}))
    stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.grounding_check_node", return_value={"violations": []}))


class PerTurnResetTests(unittest.TestCase):
    def test_retry_loop_works_again_on_second_turn(self):
        # If retry_count leaked from turn 1 (ended at 1) into turn 2, the supervisor
        # route `retry_count < MAX_RETRIES` would be false and the retry loop would be
        # dead on turn 2. start_turn must reset it to 0 so the loop fires again.
        synth_calls = {"n": 0}

        def fake_synthesiser(state):
            synth_calls["n"] += 1
            if state.get("retry_count", 0):
                return {"draft_response": "Section 1 of Example Act applies.", "citations": []}
            return {"draft_response": "You should do X.", "citations": []}

        def fake_supervisor(state):
            if "You should" in state["draft_response"]:
                return {"violations": ["advice"], "final_response": state["draft_response"]}
            return {"violations": [], "final_response": state["draft_response"]}

        with patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}), \
             patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser), \
             patch("agent.graph.citation_validator_node", return_value={"violations": []}), \
             patch("agent.graph.grounding_check_node", return_value={"violations": []}), \
             patch("agent.graph.supervisor_node", side_effect=fake_supervisor):
            app = build_graph(MemorySaver())
            config = _config("reset-thread")
            app.invoke({"query": "first question"}, config)
            turn2 = app.invoke({"query": "second question"}, config)

        # Each turn retries exactly once: 2 synthesiser calls per turn → 4 total.
        self.assertEqual(synth_calls["n"], 4)
        # Turn 2 still ended with a fresh single retry, proving the reset.
        self.assertEqual(turn2["retry_count"], 1)
        self.assertEqual(turn2["violations"], [])


class HistoryAccumulationTests(unittest.TestCase):
    def test_history_accumulates_and_nodes_see_prior_turns_only(self):
        seen_history: list[list] = []

        def fake_synthesiser(state):
            # Snapshot what history the node sees DURING the turn.
            seen_history.append(list(state.get("history", [])))
            return {"draft_response": f"Answer to: {state['query']}", "citations": []}

        def fake_supervisor(state):
            return {"violations": [], "final_response": state["draft_response"]}

        with ExitStack() as stack:
            _enter_passthrough_nodes(stack)
            stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser))
            stack.enter_context(patch("agent.graph.supervisor_node", side_effect=fake_supervisor))
            app = build_graph(MemorySaver())
            config = _config("accumulate-thread")
            app.invoke({"query": "first question"}, config)
            turn2 = app.invoke({"query": "second question"}, config)

        # Turn 1 saw no prior history; turn 2 saw exactly turn 1's two messages.
        self.assertEqual(seen_history[0], [])
        self.assertEqual(seen_history[1], [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "Answer to: first question"},
        ])
        # The current query must NOT already be in history during the turn.
        self.assertNotIn(
            {"role": "user", "content": "second question"}, seen_history[1]
        )
        # Final checkpoint holds both turns' user+assistant messages.
        self.assertEqual(turn2["history"], [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "Answer to: first question"},
            {"role": "user", "content": "second question"},
            {"role": "assistant", "content": "Answer to: second question"},
        ])


class ThreadIsolationTests(unittest.TestCase):
    def test_distinct_threads_do_not_share_history(self):
        def fake_synthesiser(state):
            return {"draft_response": f"Answer to: {state['query']}", "citations": []}

        def fake_supervisor(state):
            return {"violations": [], "final_response": state["draft_response"]}

        with ExitStack() as stack:
            _enter_passthrough_nodes(stack)
            stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser))
            stack.enter_context(patch("agent.graph.supervisor_node", side_effect=fake_supervisor))
            app = build_graph(MemorySaver())
            app.invoke({"query": "thread A question"}, _config("thread-A"))
            result_b = app.invoke({"query": "thread B question"}, _config("thread-B"))

        # Thread B's history must contain only its own turn, none of thread A's.
        self.assertEqual(result_b["history"], [
            {"role": "user", "content": "thread B question"},
            {"role": "assistant", "content": "Answer to: thread B question"},
        ])
        self.assertNotIn(
            {"role": "user", "content": "thread A question"}, result_b["history"]
        )


if __name__ == "__main__":
    unittest.main()
