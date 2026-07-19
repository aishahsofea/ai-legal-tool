import unittest

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
