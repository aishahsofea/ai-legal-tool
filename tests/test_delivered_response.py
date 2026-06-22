"""delivered_response is the single source of truth for what the user receives.

The graph (history recording) and the query lifecycle (user-facing return) both
map state -> delivered response through this helper, so the two paths can never drift.
"""
import unittest

from agent.query_policy import FINAL_FAILURE_RESPONSE, delivered_response


class DeliveredResponseTests(unittest.TestCase):
    def test_violations_yield_safe_fallback(self):
        state = {"violations": ["advice"], "final_response": "You should do X."}
        self.assertEqual(delivered_response(state), FINAL_FAILURE_RESPONSE)

    def test_clean_returns_final_response(self):
        state = {"violations": [], "final_response": "Section 1 applies."}
        self.assertEqual(delivered_response(state), "Section 1 applies.")

    def test_empty_final_falls_back_to_draft(self):
        state = {"violations": [], "final_response": "", "draft_response": "Draft text."}
        self.assertEqual(delivered_response(state), "Draft text.")


if __name__ == "__main__":
    unittest.main()
