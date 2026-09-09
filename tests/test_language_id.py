"""Tests for the BM/English scorer behind the `language_register` assertion.

The classifier tests are skipped when the fastText model is not available
(package missing, or no cached copy), so a fresh checkout runs the suite
without a 331MB download. Run the evals once to populate the cache.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import evals.language_id as language_id
from evals.language_id import (
    BM_SHARE_THRESHOLDS,
    DEFAULT_MODEL_FILE,
    DEFAULT_MODEL_REPO,
    LanguageModelUnavailable,
    _check_labels,
    _segments,
    bm_share,
)
from evals.run_evals import iter_suite

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


BM_ANSWER = (
    "Di bawah seksyen 60A Akta Pekerjaan 1955, seseorang pekerja tidak boleh "
    "dikehendaki bekerja lebih daripada lapan jam sehari. Majikan hendaklah "
    "memastikan waktu rehat diberikan kepada pekerja."
)

# The failure the wordlist check could not see: English carrying one BM word.
ENGLISH_ANSWER = (
    "Under section 60A (seksyen 60A) of the Employment Act 1955, an employee "
    "shall not be required to work more than eight hours in one day. The "
    "employer must also provide rest periods during the working day."
)

BILINGUAL_ANSWER = (
    "Di bawah seksyen 60A Akta Pekerjaan 1955: \"An employee shall not be "
    "required to work more than eight hours in one day or forty-eight hours "
    "in one week.\" Ini bermakna majikan tidak boleh menetapkan waktu kerja "
    "melebihi had tersebut. Nota: maklumat ini bukan nasihat guaman."
)


@requires_model
class BmShareTests(unittest.TestCase):
    def test_pure_bm_answer_scores_near_one(self):
        self.assertGreaterEqual(bm_share(BM_ANSWER), BM_SHARE_THRESHOLDS["bm"])

    def test_english_answer_with_one_bm_word_scores_near_zero(self):
        self.assertLess(bm_share(ENGLISH_ANSWER), BM_SHARE_THRESHOLDS["mixed"])

    def test_the_three_answer_shapes_score_in_order(self):
        # The ordering is what the scorer has to get right whatever the model
        # version; the thresholds below are calibration on top of it, and this
        # test says which of the two broke.
        self.assertLess(bm_share(ENGLISH_ANSWER), bm_share(BILINGUAL_ANSWER))
        self.assertLess(bm_share(BILINGUAL_ANSWER), bm_share(BM_ANSWER))

    def test_bilingual_answer_lands_between_the_two_thresholds(self):
        share = bm_share(BILINGUAL_ANSWER)
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


class _StubModel:
    """Predicts one fixed label set, standing in for a wrong `BM_LANGID_MODEL_REPO`."""

    def __init__(self, labels: tuple[str, ...]):
        self._labels = labels

    def predict(self, text: str, k: int = 1):
        return self._labels, tuple(1.0 / len(self._labels) for _ in self._labels)


class ModelLoadingTests(unittest.TestCase):
    def setUp(self):
        self._cache = language_id._model_cache
        self._error = language_id._load_error
        language_id._model_cache = None
        language_id._load_error = None

    def tearDown(self):
        language_id._model_cache = self._cache
        language_id._load_error = self._error

    def test_a_classifier_with_other_labels_is_rejected_by_name(self):
        with self.assertRaises(LanguageModelUnavailable) as caught:
            _check_labels(_StubModel(("__label__ms", "__label__en")), "some/repo", "model.ftz")
        # Named labels, not "no scoreable text" 40 cases later.
        self.assertIn("bahasa", str(caught.exception))
        self.assertIn("english", str(caught.exception))

    def test_the_expected_label_pair_passes(self):
        stub = _StubModel(("__label__bahasa", "__label__english", "__label__other"))
        self.assertIsNone(_check_labels(stub, DEFAULT_MODEL_REPO, DEFAULT_MODEL_FILE))

    def test_a_failed_load_is_not_retried_once_per_segment(self):
        with patch.object(
            language_id, "_download_path", side_effect=OSError("no network")
        ) as download:
            for _ in range(3):
                with self.assertRaises(LanguageModelUnavailable):
                    language_id._model()
        download.assert_called_once()

    def test_a_cached_model_is_loaded_without_a_hub_request(self):
        # try_to_load_from_cache hits disk; hf_hub_download revalidates over HTTP.
        cached = "/tmp/fasttext.ftz"
        with patch("huggingface_hub.try_to_load_from_cache", return_value=cached) as from_cache, \
             patch("huggingface_hub.hf_hub_download") as download:
            self.assertEqual(language_id._download_path("some/repo", "model.ftz"), cached)
        from_cache.assert_called_once()
        download.assert_not_called()


class EvalPreflightTests(unittest.TestCase):
    """A BM subset loads the classifier before the run spends anything."""

    def test_a_bm_subset_fails_before_the_database_and_the_first_agent_call(self):
        cases = [{"id": "bm-1", "query": "Apakah maksud fitnah?", "language": "bm"}]
        with patch(
            "evals.run_evals.ensure_language_model",
            side_effect=LanguageModelUnavailable("no model"),
        ) as ensure, patch("evals.run_evals.psycopg2.connect") as connect:
            with self.assertRaises(LanguageModelUnavailable):
                next(iter_suite("raw", cases))
        ensure.assert_called_once()
        connect.assert_not_called()

    def test_an_english_subset_never_loads_the_classifier(self):
        cases = [{"id": "en-1", "query": "What is defamation?", "language": "en"}]
        with patch("evals.run_evals.ensure_language_model") as ensure, patch(
            "evals.run_evals.psycopg2.connect", side_effect=RuntimeError("stop here")
        ):
            with self.assertRaises(RuntimeError):
                next(iter_suite("raw", cases))
        ensure.assert_not_called()
