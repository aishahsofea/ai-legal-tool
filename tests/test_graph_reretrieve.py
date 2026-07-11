"""Phase 4 — the retry routes by violation kind.

An evidence gap (bad/missing citation, unsupported claim) re-retrieves with
feedback when AGENTIC_RETRIEVAL is on; a policy/phrasing violation, or any
violation with the flag off, re-drafts against the same chunks as before.
"""
import os
import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph

_CONFIG = {"configurable": {"thread_id": "t1"}}


def _initial_state():
    return {"query": "which laws cover data privacy?"}


class ReRetrieveRoutingTests(unittest.TestCase):
    def _run(self, flag: str):
        seen = {"retriever_calls": 0, "feedback": []}

        def fake_retriever(state):
            seen["retriever_calls"] += 1
            seen["feedback"].append(state.get("retrieval_feedback", ""))
            return {"retrieved_chunks": [{"act_number": "1", "section_number": "1"}]}

        def fake_synth(state):
            return {
                "draft_response": "Section 1 of Example Act applies. Not legal advice.",
                "citations": [{"act_number": "1", "section_number": "1"}],
            }

        def fake_citation(state):
            # Evidence gap on the first pass only; clean on the retry.
            if state.get("retry_count", 0) == 0:
                v = ["Citation Section 1 of Act 1 was not in retrieved sources."]
                return {"violations": list(state.get("violations", [])) + v, "evidence_violations": v}
            return {
                "violations": list(state.get("violations", [])),
                "evidence_violations": list(state.get("evidence_violations", [])),
            }

        def passthrough_grounding(state):
            return {"violations": list(state.get("violations", []))}

        def fake_supervisor(state):
            return {"violations": list(state.get("violations", [])), "final_response": state["draft_response"]}

        with patch.dict(os.environ, {"AGENTIC_RETRIEVAL": flag}), \
             patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}), \
             patch("agent.graph.retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.agentic_retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synth), \
             patch("agent.graph.citation_validator_node", side_effect=fake_citation), \
             patch("agent.graph.grounding_check_node", side_effect=passthrough_grounding), \
             patch("agent.graph.supervisor_node", side_effect=fake_supervisor):
            app = build_graph(MemorySaver())
            result = app.invoke(_initial_state(), _CONFIG)
        return seen, result

    def test_evidence_gap_reretrieves_with_feedback_when_flag_on(self):
        seen, result = self._run("1")
        self.assertEqual(seen["retriever_calls"], 2)          # first pass + re-retrieval
        self.assertEqual(seen["feedback"][0], "")             # first pass has no feedback
        self.assertIn("not in retrieved sources", seen["feedback"][1])  # retry carries the gap
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["final_response"], "Section 1 of Example Act applies. Not legal advice.")

    def test_evidence_gap_redrafts_when_flag_off(self):
        seen, result = self._run("")
        self.assertEqual(seen["retriever_calls"], 1)          # no re-retrieval; re-draft path
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["violations"], [])

    def test_policy_violation_redrafts_even_when_flag_on(self):
        calls = {"synth": 0, "retriever": 0}

        def fake_retriever(state):
            calls["retriever"] += 1
            return {"retrieved_chunks": [{"act_number": "1", "section_number": "1"}]}

        def fake_synth(state):
            calls["synth"] += 1
            body = "Section 1 applies." if state.get("retry_count", 0) else "You should do X."
            return {"draft_response": body + " Not legal advice.", "citations": [{"act_number": "1", "section_number": "1"}]}

        def fake_supervisor(state):
            # Policy violation (advice phrase), NOT an evidence gap.
            v = ["advice"] if "You should" in state["draft_response"] else []
            return {"violations": list(state.get("violations", [])) + v, "final_response": state["draft_response"]}

        with patch.dict(os.environ, {"AGENTIC_RETRIEVAL": "1"}), \
             patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}), \
             patch("agent.graph.retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.agentic_retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synth), \
             patch("agent.graph.citation_validator_node", side_effect=lambda s: {"violations": list(s.get("violations", []))}), \
             patch("agent.graph.grounding_check_node", side_effect=lambda s: {"violations": list(s.get("violations", []))}), \
             patch("agent.graph.supervisor_node", side_effect=fake_supervisor):
            app = build_graph(MemorySaver())
            result = app.invoke(_initial_state(), _CONFIG)

        # Policy issue → re-draft (synthesiser twice), retriever ran only once.
        self.assertEqual(calls["synth"], 2)
        self.assertEqual(calls["retriever"], 1)
        self.assertEqual(result["violations"], [])


if __name__ == "__main__":
    unittest.main()
