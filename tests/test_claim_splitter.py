import json
import unittest
from pathlib import Path

from agent.nodes.claim_splitter import split_claims
from citation_receipts.locator import contains_normalized_sequence

_DATASET = Path(__file__).resolve().parent.parent / "evals" / "grounding_dataset.json"


class ClaimSplitterTests(unittest.TestCase):
    def test_keeps_only_sentences_naming_an_act_or_section(self):
        draft = (
            "Here is what the law says. Section 90A of the Evidence Act 1950 covers "
            "computer output. Practitioners often add that courts are cautious. "
            "The Act also requires a certificate."
        )
        self.assertEqual(
            split_claims(draft),
            [
                "Section 90A of the Evidence Act 1950 covers computer output.",
                "Practitioners often add that courts are cautious.",
                "The Act also requires a certificate.",
            ],
        )

    def test_bm_attribution(self):
        draft = "Ringkasnya begini. Seksyen 43 PDPA: pengguna data mesti berhenti memproses. Sekian."
        self.assertEqual(
            split_claims(draft),
            ["Seksyen 43 PDPA: pengguna data mesti berhenti memproses.", "Sekian."],
        )

    def test_abbreviations_do_not_end_a_sentence(self):
        draft = "Under s. 90A of the Evidence Act 1950, a document by Acme Sdn. Bhd. is admissible. Done."
        self.assertEqual(
            split_claims(draft),
            [
                "Under s. 90A of the Evidence Act 1950, a document by Acme Sdn. Bhd. is admissible.",
                "Done.",
            ],
        )

    def test_list_markers_and_newlines_split_claims(self):
        draft = "- Section 12 of the PDPA gives access.\n- Section 30 of the PDPA sets a fee.\n1. Background."
        self.assertEqual(
            split_claims(draft),
            ["Section 12 of the PDPA gives access.", "Section 30 of the PDPA sets a fee."],
        )

    def test_no_attribution_means_no_claims(self):
        self.assertEqual(split_claims("Courts are cautious. Seek a lawyer."), [])
        self.assertEqual(split_claims(""), [])

    def test_every_claim_is_found_in_the_draft(self):
        draft = "Intro.\n- **Section 5** of the Act says X. See s. 6(2) too.\nOutro."
        claims = split_claims(draft)
        self.assertTrue(claims)
        for claim in claims:
            self.assertTrue(contains_normalized_sequence(claim, draft), claim)

    def test_each_labelled_claim_survives_inside_a_draft(self):
        cases = json.loads(_DATASET.read_text())["cases"]
        for case in cases:
            draft = f"Here is the position.\n\n{case['claim']}\n\nThis is not legal advice."
            with self.subTest(case=case["id"]):
                self.assertEqual(split_claims(draft), [case["claim"]])


if __name__ == "__main__":
    unittest.main()


_SOURCES = [
    {"act_number": "56", "act_title": "Evidence Act 1950", "section_number": "90A"},
    {"act_number": "1", "act_title": "Revision of Laws Act 1968", "section_number": "17"},
]


def test_pair_source_reads_the_section_the_sentence_names():
    from agent.nodes.claim_splitter import pair_source

    assert pair_source("Section 90A of the Evidence Act 1950 covers it.", _SOURCES)["act_number"] == "56"
    assert pair_source("Seksyen 17 menyatakan perkara itu.", _SOURCES)["act_number"] == "1"


def test_pair_source_refuses_to_guess():
    from agent.nodes.claim_splitter import pair_source

    assert pair_source("The Act says so.", _SOURCES) is None
    assert pair_source("Section 5 says so.", _SOURCES) is None
    same_section = [*_SOURCES, {"act_number": "9", "act_title": "Other Act 2000", "section_number": "17"}]
    assert pair_source("Section 17 says so.", same_section) is None
    assert pair_source("Section 17 of the Other Act 2000 says so.", same_section)["act_number"] == "9"


def test_pair_source_uses_the_only_source_when_no_section_is_named():
    from agent.nodes.claim_splitter import pair_source

    assert pair_source("The Act says so.", _SOURCES[:1])["act_number"] == "56"


def test_unattributed_sentence_after_a_claim_is_kept_but_the_disclaimer_is_not():
    draft = (
        "No. Section 123 of the Evidence Act 1950 limits it. That permission is subject to a Minister.\n\n"
        "Background with no attribution.\n\n---\n*This is not legal advice.*"
    )

    assert split_claims(draft) == [
        "No. Section 123 of the Evidence Act 1950 limits it.",
        "That permission is subject to a Minister.",
    ]
