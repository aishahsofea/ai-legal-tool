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
    "document_id": "act-574-en-sha256-89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0",
    "extraction_id": "extraction-sha256-4ad8efde3b09933e28a63411f7162a910655c520e7a6a6d637e0ccddb27a2382",
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
        self.assertEqual(result["citations"][0]["receipt"]["document_id"], _CHUNK["document_id"])
        self.assertEqual(result["citations"][0]["receipt"]["extraction_id"], _CHUNK["extraction_id"])
        self.assertEqual(result["citations"][0]["receipt"]["evidence"], [])

    def test_non_pilot_citation_has_no_receipt(self):
        chunk = {**_CHUNK, "act_number": "999", "act_title": "EXAMPLE ACT"}
        output = _SynthesiserOutput(
            answer="Section 34 applies.",
            citation_refs=[_CitationRef(act_number="999", section_number="34")],
        )
        with patch.object(synthesiser, "_structured_llm") as mock_llm:
            mock_llm.invoke.return_value = output
            result = synthesiser.synthesiser_node({
                "query": "Section 34 Example Act",
                "retrieved_chunks": [chunk],
                "history": [],
                "response_language": "en",
            })

        self.assertNotIn("receipt", result["citations"][0])

    def test_model_formatted_citation_refs_resolve_to_retrieved_chunks(self):
        variants = [
            ("Act 574", "34"),
            ("574", "Section 34(1)"),
            (" Akta 574 ", " seksyen 34(2) "),
        ]

        for act_number, section_number in variants:
            with self.subTest(act_number=act_number, section_number=section_number):
                output = _SynthesiserOutput(
                    answer="Section 34 applies.",
                    citation_refs=[_CitationRef(
                        act_number=act_number,
                        section_number=section_number,
                    )],
                )
                with patch.object(synthesiser, "_structured_llm") as mock_llm:
                    mock_llm.invoke.return_value = output
                    result = synthesiser.synthesiser_node({
                        "query": "Section 34 Penal Code",
                        "retrieved_chunks": [_CHUNK],
                        "history": [],
                        "response_language": "en",
                    })

                self.assertEqual(len(result["citations"]), 1)
                self.assertEqual(result["citations"][0]["act_number"], "574")
                self.assertEqual(result["citations"][0]["section_number"], "34")

    def test_disabled_mode_chunk_prompt_has_no_reference_annotation(self):
        messages = synthesiser._build_messages({
            "query": "What does section 34 say?",
            "retrieved_chunks": [_CHUNK],
            "history": [],
            "response_language": "en",
        })
        self.assertNotIn("Reference context:", messages[1]["content"])

    def test_cross_act_target_prompt_preserves_version_neutral_provenance(self):
        chunk = {
            **_CHUNK,
            "_reference_context": {
                "source_document_id": "act-265-en-sha256-source",
                "source_act_number": "265",
                "related_provision_id": "act:574/section:34",
                "directions": ["outgoing"],
                "provenance_scope": "version_neutral_cross_act_independent_corpus",
            },
        }
        messages = synthesiser._build_messages({
            "query": "What does the source provision refer to?",
            "retrieved_chunks": [chunk],
            "history": [],
            "response_language": "en",
        })
        prompt = messages[1]["content"]
        self.assertIn("cross-Act identity is version-neutral", prompt)
        self.assertIn("does not establish that target version was in force", prompt)
        self.assertEqual(prompt.count(_CHUNK["content"]), 1)

    def test_reference_target_citation_still_uses_only_chunk_receipt_provenance(self):
        chunk = {
            **_CHUNK,
            "_reference_context": {
                "source_document_id": "act-265-en-sha256-source",
                "source_act_number": "265",
                "related_provision_id": "act:574/section:34",
                "directions": ["outgoing"],
                "provenance_scope": "version_neutral_cross_act_independent_corpus",
            },
        }
        output = _SynthesiserOutput(
            answer="Section 34 applies.",
            citation_refs=[_CitationRef(act_number="574", section_number="34")],
        )
        result = synthesiser._finalise(output, {
            "retrieved_chunks": [chunk],
            "response_language": "en",
        })
        citation = result["citations"][0]
        self.assertEqual(citation["receipt"]["document_id"], _CHUNK["document_id"])
        self.assertEqual(citation["receipt"]["extraction_id"], _CHUNK["extraction_id"])
        self.assertNotIn("source_document_id", citation["receipt"])


if __name__ == "__main__":
    unittest.main()
