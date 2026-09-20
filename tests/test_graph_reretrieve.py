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
from agent.nodes.grounding_check import _GroundingClaim, _GroundingOutput

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


class CommentaryGroundingFeedbackLoopTests(unittest.TestCase):
    """#56 Phase 5 / ADR 0020: 'the grounding feedback loop' (implementation
    plan section 6). A background sentence with no section attribution must
    not become an `evidence_violations` entry, or every commentary turn would
    re-retrieve to MAX_RETRIES and end in `FINAL_FAILURE_RESPONSE`. The judge
    here is mocked (grounding_check.py's system prompt is pinned separately in
    test_grounding_check.py); this proves the graph's routing and citation
    plumbing complete a commentary turn cleanly once the judge honours that
    contract, rather than only when nothing gets extracted for it to trip on.
    """

    def test_commentary_background_sentence_does_not_trigger_the_retry_loop(self):
        draft = (
            "Section 90A of the Evidence Act 1950 makes a computer-produced document "
            "admissible. A client alert from skrine.com notes that practitioners have "
            "welcomed this in commercial disputes."
        )
        citation = {
            "act_number": "56", "act_title": "EVIDENCE ACT 1950", "section_number": "90A",
            "pdf_url": "", "page_number": 1,
        }
        chunk = {
            "act_number": "56", "act_title": "EVIDENCE ACT 1950", "section_number": "90A",
            "content": "90A. A document produced by a computer shall be admissible as evidence.",
            "page_number": 1, "language": "en",
        }
        commentary_note = {
            "url": "https://skrine.com/insights/x", "title": "x", "publisher": "skrine.com",
            "published_date": "2024-01-01", "retrieved_at": "2026-09-19T00:00:00+00:00",
            "snippet": "...",
        }
        # Simulates the new grounding prompt's contract (agent/nodes/grounding_check.py
        # _SYSTEM): the judge extracts a claim only for the sentence naming a cited
        # section, and never surfaces one for the unattributed commentary sentence.
        verdict = _GroundingOutput(claims=[_GroundingClaim(
            claim="Section 90A of the Evidence Act 1950 makes a computer-produced document admissible.",
            cited_act_number="56",
            cited_section_number="90A",
            support="supported",
            reason="Direct support.",
        )])

        def fake_retriever(state):
            return {"retrieved_chunks": [chunk], "commentary": [commentary_note]}

        def fake_synth(state):
            return {"draft_response": draft, "citations": [citation]}

        def fake_citation(state):
            return {"violations": list(state.get("violations", []))}

        def fake_supervisor(state):
            return {"violations": list(state.get("violations", [])), "final_response": state["draft_response"]}

        with patch.dict(os.environ, {"AGENTIC_RETRIEVAL": "1", "WEB_COMMENTARY_ENABLED": "1"}), \
             patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}), \
             patch("agent.graph.retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.agentic_retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synth), \
             patch("agent.graph.citation_validator_node", side_effect=fake_citation), \
             patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm, \
             patch("agent.graph.supervisor_node", side_effect=fake_supervisor):
            grounding_llm.invoke.return_value = verdict
            app = build_graph(MemorySaver())
            result = app.invoke(_initial_state(), _CONFIG)

        self.assertEqual(result["violations"], [])
        self.assertEqual(result.get("retry_count", 0), 0)
        self.assertEqual(result["final_response"], draft)


if __name__ == "__main__":
    unittest.main()
