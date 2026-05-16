import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes import synthesiser
from agent.nodes.synthesiser import _CitationRef, _DISCLAIMER_BM, _DISCLAIMER_EN, _SynthesiserOutput

_CHUNK = {
    "act_number": "574",
    "act_title": "PENAL CODE",
    "section_number": "34",
    "content": "34. When a criminal act is done by several persons in furtherance of the common intention of all...",
    "page_number": 12,
    "language": "en",
    "pdf_url": "",
}

_ANSWER = "Di bawah seksyen 34 Kanun Keseksaan, setiap orang yang bertindak bersama adalah bertanggungjawab."


class SynthesiserDisclaimerTests(unittest.TestCase):
    def _run_node(self, response_language: str, answer: str = _ANSWER):
        output = _SynthesiserOutput(
            answer=answer,
            citation_refs=[_CitationRef(act_number="574", section_number="34")],
        )
        with patch.object(synthesiser, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = output
            return synthesiser.synthesiser_node({
                "query": "seksyen 34 Kanun Keseksaan",
                "retrieved_chunks": [_CHUNK],
                "history": [],
                "response_language": response_language,
            })

    def test_en_response_uses_english_disclaimer(self):
        result = self._run_node("en", answer="Section 34 of the Penal Code provides for joint liability.")
        self.assertIn("legal research only", result["draft_response"])
        self.assertNotIn("penyelidikan undang-undang", result["draft_response"])

    def test_bm_response_uses_bm_disclaimer(self):
        result = self._run_node("bm")
        self.assertIn("penyelidikan undang-undang", result["draft_response"])
        self.assertNotIn("legal research only", result["draft_response"])

    def test_mixed_response_uses_bm_disclaimer(self):
        result = self._run_node("mixed")
        self.assertIn("penyelidikan undang-undang", result["draft_response"])
        self.assertNotIn("legal research only", result["draft_response"])

    def test_missing_response_language_defaults_to_en_disclaimer(self):
        output = _SynthesiserOutput(
            answer="Section 34 applies.",
            citation_refs=[_CitationRef(act_number="574", section_number="34")],
        )
        with patch.object(synthesiser, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = output
            result = synthesiser.synthesiser_node({
                "query": "Section 34 Penal Code",
                "retrieved_chunks": [_CHUNK],
                "history": [],
            })
        self.assertIn("legal research only", result["draft_response"])

    def test_citations_resolved_from_chunks(self):
        result = self._run_node("bm")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["act_number"], "574")
        self.assertEqual(result["citations"][0]["section_number"], "34")


if __name__ == "__main__":
    unittest.main()
