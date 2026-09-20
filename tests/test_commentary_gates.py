"""Phase 4 gate tests for #56 (commentary as a non-citable source class).

Turns the section 7 acceptance criteria that need neither a running model
(Phase 5) nor the UI (Phase 7) into tests: citation presence, grounding,
per-turn state reset, and trace/SSE isolation. The tool-level allowlist/
failure-contract and retrieval-agent tool-binding criteria are already
covered by test_retrieval_tools.py's SearchCommentaryToolTests and
test_agentic_retriever.py's CommentaryToolBindingTests / Commentary
RetrievalGraphIntegrationTests (#56 Phase 3) - not duplicated here.
"""
import asyncio
import os
import unittest
from unittest.mock import patch

from agent import query_lifecycle
from agent.graph import _retry_retrieve_node, _start_turn
from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.grounding_check import (
    _GroundingClaim,
    _GroundingOutput,
    _collect_cited_sources,
    _finalise,
    grounding_check_node,
)
from agent.query_lifecycle import run_query, run_query_stream

RETRIEVED_90A = {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "90A",
    "content": "90A. A document produced by a computer shall be admissible as evidence if produced in the course of ordinary use.",
    "page_number": 1,
    "language": "en",
    "document_id": "act-56-en-sha256-fixture",
    "extraction_id": "extraction-sha256-fixture",
}

CITATION_90A = {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "90A",
    "pdf_url": "",
    "page_number": 1,
    "receipt": {
        "document_id": RETRIEVED_90A["document_id"],
        "extraction_id": RETRIEVED_90A["extraction_id"],
        "evidence": [],
    },
}

_SUPPORTED_CLAIM_TEXT = "A document produced by a computer shall be admissible as evidence."

COMMENTARY_NOTE = {
    "url": "https://skrine.com/insights/employment-act-2022-amendments",
    "title": "Employment Act 2022 Amendments: What Employers Need to Know",
    "publisher": "skrine.com",
    "published_date": "2022-09-01",
    "retrieved_at": "2026-09-19T00:00:00+00:00",
    "snippet": "The amendments extend maternity leave to 98 days...",
}


class CitationPresenceCommentaryTests(unittest.TestCase):
    def test_commentary_alone_fails_the_same_as_no_commentary_at_all(self):
        """Control pair from the implementation plan: a turn with commentary and
        no statute citation must produce the same violation as a turn with
        neither, so it hits the same fail-closed fallback."""
        base_state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [],
            "draft_response": "Background: commentary discusses recent amendments.",
            "violations": [],
        }

        result_with = citation_validator_node({**base_state, "commentary": [COMMENTARY_NOTE]})
        result_without = citation_validator_node({**base_state, "commentary": []})

        self.assertEqual(result_with["violations"], result_without["violations"])
        self.assertIn(
            "No citation found. A legal answer must cite at least one retrieved section.",
            result_with["violations"],
        )

    def test_commentary_present_does_not_block_a_valid_structured_citation(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "commentary": [COMMENTARY_NOTE],
            "draft_response": "Section 90A of the Evidence Act 1950 applies.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])


class GroundingIgnoresCommentaryTests(unittest.TestCase):
    def test_collect_cited_sources_ignores_the_commentary_channel(self):
        with_commentary = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "commentary": [COMMENTARY_NOTE],
        }
        without_commentary = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
        }

        self.assertEqual(
            _collect_cited_sources(with_commentary),
            _collect_cited_sources(without_commentary),
        )

    def test_claim_with_no_matching_citation_gets_no_evidence_even_if_judge_says_supported(self):
        """A background sentence sourced only from commentary has no structured
        citation behind it. Even an adversarial judge verdict of "supported" for
        that claim's (invented) act/section can't attach evidence: `_finalise`
        requires a real citation+chunk pair at that key (ADR 0020)."""
        state = {
            "draft_response": "Practitioners say the amendments widen coverage.",
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "commentary": [COMMENTARY_NOTE],
            "violations": [],
        }
        verdict = _GroundingOutput(claims=[_GroundingClaim(
            claim="Practitioners say the amendments widen coverage.",
            cited_act_number="999",
            cited_section_number="1",
            support="supported",
            reason="Judge hallucinated support from commentary.",
        )])

        result = _finalise(verdict, state, [])

        self.assertEqual(result["citations"][0]["receipt"]["evidence"], [])
        self.assertEqual(result["violations"], [])

    def test_grounding_check_node_output_identical_with_or_without_commentary(self):
        base_state = {
            "draft_response": _SUPPORTED_CLAIM_TEXT,
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "violations": [],
        }
        verdict = _GroundingOutput(claims=[_GroundingClaim(
            claim=_SUPPORTED_CLAIM_TEXT,
            cited_act_number="56",
            cited_section_number="90A",
            support="supported",
            reason="Direct support.",
            quote=_SUPPORTED_CLAIM_TEXT,
        )])

        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            grounding_llm.invoke.return_value = verdict
            result_without = grounding_check_node(dict(base_state))
        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            grounding_llm.invoke.return_value = verdict
            result_with = grounding_check_node({**base_state, "commentary": [COMMENTARY_NOTE]})

        self.assertEqual(result_with["violations"], result_without["violations"])
        self.assertEqual(
            result_with["citations"][0]["receipt"]["evidence"],
            result_without["citations"][0]["receipt"]["evidence"],
        )


class GraphResetTests(unittest.TestCase):
    """Mirrors reference_trace/reference_metrics reset, the prior art this
    plan copies (agent/graph.py:_start_turn, :_retry_retrieve_node)."""

    def test_start_turn_resets_commentary(self):
        state = {"commentary": [COMMENTARY_NOTE], "query": "does the PDPA apply?"}

        result = _start_turn(state)

        self.assertEqual(result["commentary"], [])

    def test_retry_retrieve_resets_commentary(self):
        state = {"commentary": [COMMENTARY_NOTE], "evidence_violations": ["gap"], "retry_count": 0}

        result = _retry_retrieve_node(state)

        self.assertEqual(result["commentary"], [])


class QueryLifecycleFlagTagTests(unittest.TestCase):
    def test_flag_off_by_default(self):
        with patch.dict(os.environ, {"WEB_COMMENTARY_ENABLED": ""}):
            cfg = query_lifecycle._config("t1")

        self.assertFalse(cfg["metadata"]["web_commentary"])
        self.assertNotIn("web_commentary", cfg["tags"])

    def test_flag_on_stamps_metadata_and_tag(self):
        with patch.dict(os.environ, {"WEB_COMMENTARY_ENABLED": "on"}):
            cfg = query_lifecycle._config("t1")

        self.assertTrue(cfg["metadata"]["web_commentary"])
        self.assertIn("web_commentary", cfg["tags"])


class SsePayloadEquivalenceTests(unittest.TestCase):
    """#56 Phase 6: `commentary` is added to QueryResult / the SSE `response`
    event only when the turn produced at least one note. An empty or absent
    channel - always the case with WEB_COMMENTARY_ENABLED off, since nothing
    ever writes to it - must leave both payloads identical to the pre-Phase-6
    shape, so the flag stays a true no-op when off (acceptance criterion 1)."""

    def test_run_query_omits_commentary_key_when_empty(self):
        final_state = {
            "query_type": "topical",
            "final_response": "Section 1 of Example Act applies.",
            "draft_response": "Section 1 of Example Act applies.",
            "citations": [],
            "violations": [],
            "commentary": [],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertNotIn("commentary", result)

    def test_run_query_surfaces_commentary_when_present(self):
        final_state = {
            "query_type": "topical",
            "final_response": "Section 1 of Example Act applies.",
            "draft_response": "Section 1 of Example Act applies.",
            "citations": [],
            "violations": [],
            "commentary": [COMMENTARY_NOTE],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertEqual(result["commentary"], [COMMENTARY_NOTE])

    def test_stream_response_event_omits_commentary_key_when_empty(self):
        async def fake_astream(_input, _config, stream_mode=None):
            yield ("updates", {
                "supervisor": {
                    "final_response": "Section 1 of Example Act applies.",
                    "citations": [],
                    "violations": [],
                    "commentary": [],
                },
            })

        async def _collect():
            with patch("agent.query_lifecycle.graph") as graph:
                graph.astream = fake_astream
                return [event async for event in run_query_stream("What does the law say?", "t1")]

        events = asyncio.run(_collect())

        responses = [e for e in events if e["type"] == "response"]
        self.assertEqual(len(responses), 1)
        self.assertNotIn("commentary", responses[0])

    def test_stream_response_event_surfaces_commentary_when_present(self):
        async def fake_astream(_input, _config, stream_mode=None):
            yield ("updates", {
                "supervisor": {
                    "final_response": "Section 1 of Example Act applies.",
                    "citations": [],
                    "violations": [],
                    "commentary": [COMMENTARY_NOTE],
                },
            })

        async def _collect():
            with patch("agent.query_lifecycle.graph") as graph:
                graph.astream = fake_astream
                return [event async for event in run_query_stream("What does the law say?", "t1")]

        events = asyncio.run(_collect())

        responses = [e for e in events if e["type"] == "response"]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["commentary"], [COMMENTARY_NOTE])


if __name__ == "__main__":
    unittest.main()
