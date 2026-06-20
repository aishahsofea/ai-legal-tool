"""record_turn stores assistant history disclaimer-free.

The synthesiser appends a disclaimer to every compliant answer (Supervisor Rule 3
validates its presence). Storing that boilerplate in history makes every later
node re-read it, so _record_turn strips it at record-time — while the disclaimer
still reaches the user in final_response.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph
from agent.query_policy import _DISCLAIMER_EN


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _passthrough(stack: ExitStack) -> None:
    stack.enter_context(patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}))
    stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
    stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
    stack.enter_context(patch("agent.graph.grounding_check_node", return_value={"violations": []}))


class RecordTurnStripTests(unittest.TestCase):
    def test_disclaimer_stripped_from_history_but_kept_in_final_response(self):
        answer = "Section 5 of the PDPA governs consent."
        draft = answer + _DISCLAIMER_EN

        def fake_synthesiser(state):
            return {"draft_response": draft, "citations": []}

        def fake_supervisor(state):
            return {"violations": [], "final_response": state["draft_response"]}

        with ExitStack() as stack:
            _passthrough(stack)
            stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser))
            stack.enter_context(patch("agent.graph.supervisor_node", side_effect=fake_supervisor))
            app = build_graph(MemorySaver())
            result = app.invoke({"query": "what about consent?"}, _config("strip-thread"))

        # The user still receives the disclaimer (Supervisor Rule 3 regression guard).
        self.assertEqual(result["final_response"], draft)
        # History stores the clean answer — disclaimer stripped.
        assistant_turns = [m for m in result["history"] if m["role"] == "assistant"]
        self.assertEqual(assistant_turns[-1]["content"], answer)
        self.assertNotIn("does not constitute legal advice", assistant_turns[-1]["content"])

    def test_escalation_text_stored_unchanged(self):
        # Escalation carries no disclaimer, so the strip is a no-op.
        with patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "escalate"}):
            app = build_graph(MemorySaver())
            result = app.invoke({"query": "am i liable under section 300?"}, _config("escalate-thread"))

        assistant_turns = [m for m in result["history"] if m["role"] == "assistant"]
        self.assertEqual(assistant_turns[-1]["content"], result["final_response"])


if __name__ == "__main__":
    unittest.main()
