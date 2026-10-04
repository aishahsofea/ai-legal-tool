import copy
import json
import unittest

from evals.validate_grounding_dataset import (
    GROUNDING_PATH,
    HARD_NEGATIVE_METHODS,
    LANGUAGES,
    MIN_CASES,
    VERDICTS,
    review_table,
    validate,
)

_METHODS = {"supported": "drafted", "partial": "overstated", "unsupported": "changed_number"}


def _case(i: int, verdict: str, language: str, method: str | None = None) -> dict:
    return {
        "id": f"g{i}", "language": language, "claim": f"claim {i}",
        "act_number": "574", "act_title": "PENAL CODE", "section_number": "34",
        "source_language": "en", "source_text": "34. When a criminal act is done by several persons",
        "verdict": verdict, "review_status": "proposed",
        "origin": {"method": method or _METHODS[verdict], "detail": "test"},
    }


def _valid_data() -> dict:
    cases = [_case(i, VERDICTS[i % 3], LANGUAGES[i % 3]) for i in range(MIN_CASES)]
    for i, method in enumerate(HARD_NEGATIVE_METHODS * 3):
        cases[i * 3 + 1]["origin"]["method"] = method
        cases[i * 3 + 2]["origin"]["method"] = method
    return {"schema_version": 1, "cases": cases}


class GroundingDatasetValidatorTests(unittest.TestCase):
    def test_shipped_dataset_is_valid(self):
        data = json.loads(GROUNDING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate(data), [])

    def test_minimal_valid_set_passes(self):
        self.assertEqual(validate(_valid_data()), [])

    def test_unknown_verdict_is_rejected(self):
        data = _valid_data()
        data["cases"][0]["verdict"] = "mostly"
        self.assertTrue(any("verdict" in e for e in validate(data)))

    def test_supported_claim_must_be_drafted(self):
        data = _valid_data()
        data["cases"][0]["origin"]["method"] = "changed_number"
        self.assertTrue(any("supported claim" in e for e in validate(data)))

    def test_negative_claim_needs_a_negative_method(self):
        data = _valid_data()
        data["cases"][1]["origin"]["method"] = "drafted"
        self.assertTrue(any("origin.method" in e for e in validate(data)))

    def test_duplicate_id_and_claim_are_rejected(self):
        data = _valid_data()
        data["cases"][1]["id"] = data["cases"][0]["id"]
        data["cases"][3]["claim"] = data["cases"][2]["claim"]
        errors = validate(data)
        self.assertTrue(any("duplicate id" in e for e in errors))
        self.assertTrue(any("duplicate claim" in e for e in errors))

    def test_source_must_carry_the_cited_section_number(self):
        data = _valid_data()
        data["cases"][0]["section_number"] = "99"
        self.assertTrue(any("does not contain section" in e for e in validate(data)))

    def test_judgement_call_needs_a_note(self):
        data = _valid_data()
        data["cases"][0]["judgement_call"] = True
        self.assertTrue(any("judgement_call" in e for e in validate(data)))

    def test_too_few_cases_or_verdicts_are_rejected(self):
        data = _valid_data()
        data["cases"] = [c for c in data["cases"] if c["verdict"] != "partial"]
        errors = validate(data)
        self.assertTrue(any("verdict partial" in e for e in errors))
        self.assertTrue(any("need at least" in e for e in errors))

    def test_require_reviewed_fails_on_proposed_labels(self):
        data = _valid_data()
        self.assertTrue(any("not reviewed" in e for e in validate(data, require_reviewed=True)))
        for case in data["cases"]:
            case["review_status"] = "reviewed"
        self.assertEqual(validate(data, require_reviewed=True), [])

    def test_review_table_groups_claims_under_one_source(self):
        cases = copy.deepcopy(_valid_data()["cases"][:3])
        table = review_table(cases)
        self.assertEqual(table.count("### PENAL CODE"), 1)
        for case in cases:
            self.assertIn(case["id"], table)


if __name__ == "__main__":
    unittest.main()
