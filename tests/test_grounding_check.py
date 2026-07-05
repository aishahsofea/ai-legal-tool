import unittest
from unittest.mock import Mock, patch

from agent.nodes.grounding_check import _GroundingClaim, _GroundingOutput, _collect_cited_sources, grounding_check_node


RETRIEVED_90A = {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "90A",
    "content": "90A. A document produced by a computer shall be admissible as evidence if produced in the course of ordinary use.",
    "page_number": 1,
    "language": "en",
}

CITATION_90A = {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "90A",
    "pdf_url": "",
    "page_number": 1,
}


class GroundingCheckTests(unittest.TestCase):
    def test_collects_only_cited_retrieved_sources(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A, {**RETRIEVED_90A, "section_number": "3"}],
            "citations": [CITATION_90A],
        }

        sources = _collect_cited_sources(state)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["section_number"], "90A")
        self.assertEqual(sources[0]["content"], RETRIEVED_90A["content"])

    def test_supported_claims_pass(self):
        state = {
            "draft_response": "Section 90A of the Evidence Act 1950 allows computer-produced documents as evidence.",
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "violations": [],
        }
        verdict = _GroundingOutput(claims=[
            _GroundingClaim(
                claim="Section 90A allows computer-produced documents as evidence.",
                cited_act_number="56",
                cited_section_number="90A",
                support="supported",
                reason="The section states this directly.",
            )
        ])

        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            grounding_llm.invoke.return_value = verdict
            result = grounding_check_node(state)

        self.assertEqual(result["violations"], [])
        grounding_llm.invoke.assert_called_once()

    def test_partial_or_unsupported_claims_become_violations(self):
        state = {
            "draft_response": "Section 90A of the Evidence Act 1950 makes all computer documents automatically conclusive.",
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "violations": [],
        }
        verdict = _GroundingOutput(claims=[
            _GroundingClaim(
                claim="Section 90A makes all computer documents automatically conclusive.",
                cited_act_number="56",
                cited_section_number="90A",
                support="unsupported",
                reason="The source concerns admissibility, not conclusive proof.",
            )
        ])

        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            grounding_llm.invoke.return_value = verdict
            result = grounding_check_node(state)

        self.assertEqual(len(result["violations"]), 1)
        self.assertIn("unsupported claim citing Section 90A of Act 56", result["violations"][0])

    def test_skips_llm_when_prior_violations_exist(self):
        state = {
            "draft_response": "Section 90A of the Evidence Act 1950 applies.",
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "violations": ["Citation error."],
        }

        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            result = grounding_check_node(state)

        self.assertEqual(result["violations"], ["Citation error."])
        grounding_llm.invoke.assert_not_called()

    def test_llm_failure_fails_open(self):
        """A judge malfunction must not be mistaken for an ungrounded answer."""
        state = {
            "draft_response": "Section 90A of the Evidence Act 1950 applies.",
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [CITATION_90A],
            "violations": [],
        }

        with patch("agent.nodes.grounding_check._grounding_llm") as grounding_llm:
            grounding_llm.invoke.side_effect = RuntimeError("judge unavailable")
            result = grounding_check_node(state)

        self.assertEqual(result["violations"], [])

    def test_claims_coerced_from_json_string(self):
        """Some models return the claims list as a JSON-encoded string; accept it."""
        raw = (
            '[{"claim": "x", "cited_act_number": "56", "cited_section_number": "90A", '
            '"support": "supported", "reason": "ok"}]'
        )
        parsed = _GroundingOutput.model_validate({"claims": raw})

        self.assertEqual(len(parsed.claims), 1)
        self.assertEqual(parsed.claims[0].support, "supported")


if __name__ == "__main__":
    unittest.main()
