"""Graph-level wiring for the contextualize node.

Locks two invariants:
  - the retriever searches on the resolved Standalone Query, not the raw follow-up
  - state["query"] is never overwritten — history records the raw query the user typed
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


class ContextualizeWiringTests(unittest.TestCase):
    def test_retriever_gets_standalone_query_history_keeps_raw(self):
        seen = []  # (standalone_query, query) the retriever observed each turn

        def fake_retriever(state):
            seen.append((state.get("standalone_query", ""), state["query"]))
            return {"retrieved_chunks": []}

        def fake_contextualize(state):
            # Turn 2 resolves the elliptical follow-up; turn 1 has no history.
            if state.get("history"):
                return {"standalone_query": "Does the PDPA apply to criminal cases?"}
            return {"standalone_query": ""}

        def fake_synthesiser(state):
            return {"draft_response": f"Section 5 of the PDPA. ({state['query']})", "citations": []}

        def fake_supervisor(state):
            return {"violations": [], "final_response": state["draft_response"]}

        with ExitStack() as stack:
            stack.enter_context(patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}))
            stack.enter_context(patch("agent.graph.contextualize_node", side_effect=fake_contextualize))
            stack.enter_context(patch("agent.graph.retriever_node", side_effect=fake_retriever))
            stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser))
            stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
            stack.enter_context(patch("agent.graph.grounding_check_node", return_value={"violations": []}))
            stack.enter_context(patch("agent.graph.supervisor_node", side_effect=fake_supervisor))
            app = build_graph(MemorySaver())
            config = _config("wiring-thread")
            app.invoke({"query": "What does Section 5 of the PDPA say?"}, config)
            result = app.invoke({"query": "what about criminal cases?"}, config)

        # Turn 1: no standalone query → retriever used the raw query.
        self.assertEqual(seen[0], ("", "What does Section 5 of the PDPA say?"))
        # Turn 2: retriever searched on the resolved standalone query...
        self.assertEqual(seen[1][0], "Does the PDPA apply to criminal cases?")
        # ...while state["query"] stayed the raw follow-up.
        self.assertEqual(seen[1][1], "what about criminal cases?")
        # History recorded the RAW query the user typed, not the rewrite.
        user_turns = [m["content"] for m in result["history"] if m["role"] == "user"]
        self.assertEqual(user_turns, [
            "What does Section 5 of the PDPA say?",
            "what about criminal cases?",
        ])

    def test_escalation_short_circuits_before_contextualize(self):
        called = {"n": 0}

        def fake_contextualize(state):
            called["n"] += 1
            return {"standalone_query": ""}

        with ExitStack() as stack:
            stack.enter_context(patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "escalate"}))
            stack.enter_context(patch("agent.graph.contextualize_node", side_effect=fake_contextualize))
            app = build_graph(MemorySaver())
            app.invoke({"query": "am i liable under section 300?"}, _config("escalate-wiring"))

        self.assertEqual(called["n"], 0)


if __name__ == "__main__":
    unittest.main()
