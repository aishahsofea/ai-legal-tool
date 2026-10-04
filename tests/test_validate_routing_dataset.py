import copy
import json
import unittest

from evals.validate_routing_dataset import (
    DATASET_PATH,
    MIN_CASES,
    ROUTING_PATH,
    QUERY_TYPES,
    review_table,
    validate,
)

DATASET_IDS = {c["id"] for c in json.loads(DATASET_PATH.read_text(encoding="utf-8"))["cases"]}


def _case(i: int, query_type: str, language: str) -> dict:
    return {
        "id": f"c{i}", "language": language, "query": f"query {i}", "query_type": query_type,
        "source": "hand", "review_status": "proposed",
    }


def _valid_data() -> dict:
    cases = [_case(i, QUERY_TYPES[i % 5], ("en", "bm", "mixed")[i % 3]) for i in range(MIN_CASES)]
    return {"schema_version": 1, "cases": cases}


class RoutingDatasetValidatorTests(unittest.TestCase):
    def test_shipped_dataset_is_valid(self):
        data = json.loads(ROUTING_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate(data, DATASET_IDS), [])

    def test_minimal_valid_set_passes(self):
        self.assertEqual(validate(_valid_data(), DATASET_IDS), [])

    def test_escalate_is_not_a_routing_label(self):
        data = _valid_data()
        data["cases"][0]["query_type"] = "escalate"
        self.assertTrue(any("query_type" in e for e in validate(data, DATASET_IDS)))

    def test_duplicate_id_and_query_are_rejected(self):
        data = _valid_data()
        data["cases"][1]["id"] = data["cases"][0]["id"]
        data["cases"][2]["query"] = data["cases"][3]["query"] = "same"
        data["cases"][2]["language"] = data["cases"][3]["language"]
        errors = validate(data, DATASET_IDS)
        self.assertTrue(any("duplicate id" in e for e in errors))
        self.assertTrue(any("duplicate query" in e for e in errors))

    def test_same_query_with_different_history_is_allowed(self):
        data = _valid_data()
        data["cases"][0]["query"] = data["cases"][1]["query"] = "what is the penalty?"
        data["cases"][1]["history"] = [{"role": "user", "content": "section 420 Penal Code"}]
        self.assertFalse(any("duplicate query" in e for e in validate(data, DATASET_IDS)))

    def test_eval_dataset_source_id_must_exist(self):
        data = _valid_data()
        data["cases"][0].update(source="eval_dataset", source_id="nope")
        self.assertTrue(any("source_id" in e for e in validate(data, DATASET_IDS)))

    def test_history_tag_requires_history(self):
        data = _valid_data()
        data["cases"][0]["tags"] = ["history"]
        self.assertTrue(any("no history" in e for e in validate(data, DATASET_IDS)))

    def test_too_few_cases_or_thin_class_is_reported(self):
        data = _valid_data()
        data["cases"] = data["cases"][: MIN_CASES - 1]
        self.assertTrue(any("at least" in e for e in validate(data, DATASET_IDS)))
        data = _valid_data()
        for c in data["cases"]:
            if c["query_type"] == "clarify":
                c["query_type"] = "topical"
        self.assertTrue(any("query_type clarify" in e for e in validate(data, DATASET_IDS)))

    def test_require_reviewed_flags_proposed_cases(self):
        data = _valid_data()
        self.assertTrue(any("not reviewed" in e for e in validate(data, DATASET_IDS, require_reviewed=True)))
        for c in data["cases"]:
            c["review_status"] = "reviewed"
        self.assertEqual(validate(copy.deepcopy(data), DATASET_IDS, require_reviewed=True), [])

    def test_review_table_escapes_pipes_and_shows_history(self):
        case = _case(0, "clarify", "en")
        case["query"] = "a | b"
        case["history"] = [{"role": "user", "content": "hi"}]
        table = review_table([case])
        self.assertIn("a \\| b", table)
        self.assertIn("history: user: hi", table)


if __name__ == "__main__":
    unittest.main()
