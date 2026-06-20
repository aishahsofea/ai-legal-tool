"""Unit tests for strip_disclaimer — removes the exact disclaimer suffix the
synthesiser appended, so history is stored clean (no repeated boilerplate)."""
import unittest

from agent.query_policy import _DISCLAIMER_BM, _DISCLAIMER_EN, strip_disclaimer


class StripDisclaimerTests(unittest.TestCase):
    def test_strips_english_disclaimer_suffix(self):
        answer = "Section 5 of the PDPA governs consent."
        self.assertEqual(strip_disclaimer(answer + _DISCLAIMER_EN), answer)

    def test_strips_bahasa_disclaimer_suffix(self):
        answer = "Seksyen 5 PDPA mengawal persetujuan."
        self.assertEqual(strip_disclaimer(answer + _DISCLAIMER_BM), answer)

    def test_returns_text_unchanged_when_no_disclaimer(self):
        text = "This escalation response carries no disclaimer."
        self.assertEqual(strip_disclaimer(text), text)

    def test_only_strips_when_disclaimer_is_a_suffix(self):
        # Disclaimer text appearing mid-string (not at the end) is left intact.
        text = _DISCLAIMER_EN.strip() + " and then more text follows."
        self.assertEqual(strip_disclaimer(text), text)


if __name__ == "__main__":
    unittest.main()
