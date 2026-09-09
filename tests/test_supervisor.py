import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.nodes.supervisor import supervisor_node
from agent.query_policy import _DISCLAIMER_BM, _DISCLAIMER_EN


class SupervisorRule3Tests(unittest.TestCase):
    def test_en_draft_with_en_disclaimer_passes(self):
        draft = "Section 3 applies here." + _DISCLAIMER_EN
        result = supervisor_node({"draft_response": draft, "violations": []})
        self.assertEqual(result["violations"], [])

    def test_bm_draft_with_bm_disclaimer_passes(self):
        draft = "Seksyen 3 terpakai di sini." + _DISCLAIMER_BM
        result = supervisor_node({"draft_response": draft, "violations": []})
        self.assertEqual(result["violations"], [])

    def test_mixed_draft_with_bm_disclaimer_passes(self):
        draft = "Section 3 applies. Seksyen ini relevan." + _DISCLAIMER_BM
        result = supervisor_node({"draft_response": draft, "violations": []})
        self.assertEqual(result["violations"], [])

    def test_en_draft_with_no_disclaimer_fails(self):
        draft = "Section 3 applies here, no disclaimer attached."
        result = supervisor_node({"draft_response": draft, "violations": []})
        self.assertIn(
            "Missing disclaimer that this is not legal advice.", result["violations"]
        )


if __name__ == "__main__":
    unittest.main()
