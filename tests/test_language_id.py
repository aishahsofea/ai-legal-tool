"""Tests for the BM/English scorer behind the `language_register` assertion.

The classifier tests are skipped when the fastText model is not available
(package missing, or no cached copy), so a fresh checkout runs the suite
without a 331MB download. Run the evals once to populate the cache.
"""
import json
import unittest
from pathlib import Path

from evals.language_id import (
    BM_SHARE_THRESHOLDS,
    DEFAULT_MODEL_FILE,
    DEFAULT_MODEL_REPO,
    LanguageModelUnavailable,
    _segments,
    bm_share,
)

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset.json"


def _model_available() -> bool:
    """Cache-only: probing with `bm_share` would pull 331MB the first time
    anyone runs the suite. An eval run downloads it; `pytest` should not."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    if try_to_load_from_cache(DEFAULT_MODEL_REPO, DEFAULT_MODEL_FILE) is None:
        return False
    try:
        bm_share("Ini adalah satu ayat dalam Bahasa Malaysia.")
    except LanguageModelUnavailable:
        return False
    return True


MODEL_AVAILABLE = _model_available()
requires_model = unittest.skipUnless(MODEL_AVAILABLE, "fastText language model unavailable")


class SegmentTests(unittest.TestCase):
    """Segmentation is what lets a bilingual answer score as bilingual, so it
    is tested on its own — no model needed."""

    def test_splits_on_sentence_enders_and_newlines(self):
        self.assertEqual(
            _segments("Satu ayat penuh. Ayat kedua di sini\nBaris ketiga di sini"),
            ["Satu ayat penuh.", "Ayat kedua di sini", "Baris ketiga di sini"],
        )

    def test_drops_fragments_too_short_to_classify(self):
        self.assertEqual(_segments("Ya. 60A. Ini ayat yang cukup panjang."), ["Ini ayat yang cukup panjang."])

    def test_empty_text_has_no_segments(self):
        self.assertEqual(_segments(""), [])
        self.assertEqual(_segments("   \n  "), [])


@requires_model
class BmShareTests(unittest.TestCase):
    def test_pure_bm_answer_scores_near_one(self):
        share = bm_share(
            "Di bawah seksyen 60A Akta Pekerjaan 1955, seseorang pekerja tidak boleh "
            "dikehendaki bekerja lebih daripada lapan jam sehari. Majikan hendaklah "
            "memastikan waktu rehat diberikan kepada pekerja."
        )
        self.assertGreaterEqual(share, BM_SHARE_THRESHOLDS["bm"])

    def test_english_answer_with_one_bm_word_scores_near_zero(self):
        # The failure the wordlist check could not see.
        share = bm_share(
            "Under section 60A (seksyen 60A) of the Employment Act 1955, an employee "
            "shall not be required to work more than eight hours in one day. The "
            "employer must also provide rest periods during the working day."
        )
        self.assertLess(share, BM_SHARE_THRESHOLDS["mixed"])

    def test_bilingual_answer_lands_between_the_two_thresholds(self):
        share = bm_share(
            "Di bawah seksyen 60A Akta Pekerjaan 1955: \"An employee shall not be "
            "required to work more than eight hours in one day or forty-eight hours "
            "in one week.\" Ini bermakna majikan tidak boleh menetapkan waktu kerja "
            "melebihi had tersebut. Nota: maklumat ini bukan nasihat guaman."
        )
        self.assertGreaterEqual(share, BM_SHARE_THRESHOLDS["mixed"])
        self.assertLess(share, BM_SHARE_THRESHOLDS["bm"])

    def test_unscoreable_text_returns_none(self):
        self.assertIsNone(bm_share(""))
        self.assertIsNone(bm_share("60A."))


class DatasetLanguageLabelTests(unittest.TestCase):
    """`language` is what decides which cases the assertion gates, so a case
    that forgets it silently drops out of the BM gate."""

    def test_every_case_declares_a_language(self):
        cases = json.loads(DATASET.read_text(encoding="utf-8"))["cases"]
        self.assertEqual([case["id"] for case in cases if not case.get("language")], [])
