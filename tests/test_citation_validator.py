import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.nodes import citation_validator
from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.supervisor import supervisor_node


RETRIEVED_90A = {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "90A",
    "content": "90A. Computer-produced documents are admissible...",
    "page_number": 1,
    "language": "en",
}


class CitationValidatorTests(unittest.TestCase):
    def test_valid_structured_citation_passes(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [{
                "act_number": "56",
                "act_title": "EVIDENCE ACT 1950",
                "section_number": "90A",
                "pdf_url": "",
                "page_number": 1,
            }],
            "draft_response": "Section 90A of the Evidence Act 1950 allows computer-produced documents.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])

    def test_structured_citation_must_be_in_retrieved_chunks(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [{
                "act_number": "56",
                "act_title": "EVIDENCE ACT 1950",
                "section_number": "114A",
                "pdf_url": "",
                "page_number": 1,
            }],
            "draft_response": "Section 114A of the Evidence Act 1950 says something.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertIn(
            "Citation Section 114A of Act 56 was not in retrieved sources.",
            result["violations"],
        )

    def test_empty_citations_fails_presence_check(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [],
            "draft_response": "There is no relevant provision in the retrieved sections.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertIn(
            "No citation found. A legal answer must cite at least one retrieved section.",
            result["violations"],
        )

    def test_non_adjacent_prose_citation_still_passes_when_structured_present(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [{
                "act_number": "56",
                "act_title": "EVIDENCE ACT 1950",
                "section_number": "90A",
                "pdf_url": "",
                "page_number": 1,
            }],
            "draft_response": "The Evidence Act 1950 sets this out under section 90A (90A).",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])

    def test_formatted_structured_citation_matches_retrieved_chunk(self):
        state = {
            "retrieved_chunks": [RETRIEVED_90A],
            "citations": [{
                "act_number": " Act 56 ",
                "act_title": "EVIDENCE ACT 1950",
                "section_number": "Section 90a(1)",
                "pdf_url": "",
                "page_number": 1,
            }],
            "draft_response": "Section 90A of the Evidence Act 1950 applies.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])

    def test_act_number_with_a_separator_is_not_reported_unknown(self):
        """Step 2 stores '49/1965' under an escaped filename, so the lookup has
        to escape the cited number the same way (#70)."""
        with tempfile.TemporaryDirectory() as tmp:
            metadata_dir = Path(tmp)
            (metadata_dir / "49%2F1965.json").write_text(
                json.dumps({"act_number": "49/1965"}), encoding="utf-8"
            )
            chunk = {"act_number": "49/1965", "section_number": "3", "content": "3. ..."}
            state = {
                "retrieved_chunks": [chunk],
                "citations": [{"act_number": "49/1965", "section_number": "3"}],
                "draft_response": "Section 3 of Act 49/1965 applies.",
                "violations": [],
            }

            with mock.patch.object(citation_validator, "METADATA_DIR", metadata_dir):
                result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])

    def test_act_with_no_metadata_file_is_reported_unknown(self):
        """The escape must not turn the unknown-Act check into a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            chunk = {"act_number": "49/1965", "section_number": "3", "content": "3. ..."}
            state = {
                "retrieved_chunks": [chunk],
                "citations": [{"act_number": "49/1965", "section_number": "3"}],
                "draft_response": "Section 3 of Act 49/1965 applies.",
                "violations": [],
            }

            with mock.patch.object(citation_validator, "METADATA_DIR", Path(tmp)):
                result = citation_validator_node(state)

        self.assertIn("Citation references unknown Act 49/1965.", result["violations"])

    def test_schedule_paragraph_citation_matches_its_own_path(self):
        chunk = {
            "act_number": "1", "act_title": "FIXTURE ACT", "section_number": "",
            "path": "sched.1/para.1", "content": "1. Fixture schedule content.",
        }
        state = {
            "retrieved_chunks": [chunk],
            "citations": [{
                "act_number": "1", "act_title": "FIXTURE ACT",
                "section_number": "", "path": "sched.1/para.1",
                "pdf_url": "", "page_number": 1,
            }],
            "draft_response": "Paragraph 1 of the First Schedule applies.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertEqual(result["violations"], [])

    def test_schedule_paragraph_citation_does_not_match_a_sibling_paragraph(self):
        # Both chunks share an empty section_number - only `path` tells them
        # apart, which is the collision this issue exists to fix (ADR 0018).
        chunk = {
            "act_number": "1", "act_title": "FIXTURE ACT", "section_number": "",
            "path": "sched.1/para.1", "content": "1. Fixture schedule content.",
        }
        state = {
            "retrieved_chunks": [chunk],
            "citations": [{
                "act_number": "1", "act_title": "FIXTURE ACT",
                "section_number": "", "path": "sched.1/para.2",
                "pdf_url": "", "page_number": 1,
            }],
            "draft_response": "Paragraph 2 of the First Schedule applies.",
            "violations": [],
        }

        result = citation_validator_node(state)

        self.assertTrue(any("was not in retrieved sources" in v for v in result["violations"]))

    def test_supervisor_preserves_existing_citation_violations(self):
        state = {
            "draft_response": (
                "Section 90A of the Evidence Act 1950 applies.\n\n"
                "This information is for legal research only and does not constitute legal advice."
            ),
            "violations": ["Citation Section 114A of Act 56 was not in retrieved sources."],
        }

        result = supervisor_node(state)

        self.assertIn(
            "Citation Section 114A of Act 56 was not in retrieved sources.",
            result["violations"],
        )


if __name__ == "__main__":
    unittest.main()
