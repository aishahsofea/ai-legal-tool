import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.nodes import currency_check
from agent.nodes.currency_check import currency_check_node

GST_TIMELINE = [
    {"date": "20/06/2014", "log_type": "ORIGINAL", "pdf_url": "https://example/act762-original.pdf"},
    {"date": "05/06/2017", "log_type": "REPRINT ONLINE", "pdf_url": "https://example/act762-reprint.pdf"},
    {"date": "06/01/2018", "log_type": "REPEALED", "pdf_url": "https://example/act762-repealed.pdf"},
]


def _write_metadata(metadata_dir: Path, act_number: str, timeline: list, timeline_bm: list | None = None) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / f"{act_number}.json").write_text(
        json.dumps({
            "act_number": act_number,
            "timeline": timeline,
            "timeline_bm": timeline if timeline_bm is None else timeline_bm,
        }),
        encoding="utf-8",
    )


def _state(act_number: str, language: str = "en", section: str = "1") -> dict:
    return {
        "citations": [{"act_number": act_number, "section_number": section, "pdf_url": "", "page_number": 1}],
        "retrieved_chunks": [{
            "act_number": act_number, "section_number": section,
            "language": language, "content": "...",
        }],
    }


class CurrencyCheckNodeTests(unittest.TestCase):
    def test_flag_off_is_a_no_op(self):
        with mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "0"}):
            self.assertEqual(currency_check_node(_state("762")), {})

    def test_repealed_act_is_labelled_repealed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "762", GST_TIMELINE)
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(_state("762"))

        self.assertEqual(result["currency_labels"], [{
            "act_number": "762",
            "label": "repealed",
            "detail_url": "https://example/act762-repealed.pdf",
            "as_of_date": "06/01/2018",
        }])

    def test_superseded_reads_the_same_as_repealed(self):
        timeline = [
            {"date": "01/01/2020", "log_type": "ORIGINAL", "pdf_url": "https://example/orig.pdf"},
            {"date": "30/11/2021", "log_type": "SUPERSEDED", "pdf_url": "https://example/superseded.pdf"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "335", timeline)
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(_state("335"))

        self.assertEqual(result["currency_labels"][0]["label"], "repealed")

    def test_normal_act_is_unknown(self):
        timeline = [
            {"date": "20/06/2014", "log_type": "ORIGINAL", "pdf_url": "https://example/orig.pdf"},
            {"date": "04/01/2017", "log_type": "AMENDMENTS", "pdf_url": "https://example/amend.pdf"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "1", timeline)
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(_state("1"))

        self.assertEqual(result["currency_labels"], [{
            "act_number": "1", "label": "unknown", "detail_url": "", "as_of_date": "",
        }])

    def test_missing_metadata_file_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(_state("999"))

        self.assertEqual(result["currency_labels"][0]["label"], "unknown")

    def test_bm_citation_reads_the_bm_timeline(self):
        """A BM-language chunk is checked against timeline_bm, not timeline -- the
        two can legitimately disagree (#67's same-date collapse can drop an entry
        from one language's page and not the other)."""
        en_timeline = [{"date": "01/01/2020", "log_type": "ORIGINAL", "pdf_url": "https://example/en.pdf"}]
        bm_timeline = [
            {"date": "01/01/2020", "log_type": "ORIGINAL", "pdf_url": "https://example/bm.pdf"},
            {"date": "01/02/2021", "log_type": "REPEALED", "pdf_url": "https://example/bm-repealed.pdf"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "50", en_timeline, bm_timeline)
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                en_result = currency_check_node(_state("50", language="en"))
                bm_result = currency_check_node(_state("50", language="bm"))

        self.assertEqual(en_result["currency_labels"][0]["label"], "unknown")
        self.assertEqual(bm_result["currency_labels"][0]["label"], "repealed")

    def test_duplicate_acts_across_citations_produce_one_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "762", GST_TIMELINE)
            state = {
                "citations": [
                    {"act_number": "762", "section_number": "3", "pdf_url": "", "page_number": 1},
                    {"act_number": "762", "section_number": "10", "pdf_url": "", "page_number": 2},
                ],
                "retrieved_chunks": [
                    {"act_number": "762", "section_number": "3", "language": "en", "content": "..."},
                    {"act_number": "762", "section_number": "10", "language": "en", "content": "..."},
                ],
            }
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(state)

        self.assertEqual(len(result["currency_labels"]), 1)

    def test_unparseable_date_does_not_suppress_a_real_repeal(self):
        timeline = [{"date": "not-a-date", "log_type": "REPEALED", "pdf_url": "https://example/repealed.pdf"}]
        with tempfile.TemporaryDirectory() as tmp:
            _write_metadata(Path(tmp), "1", timeline)
            with mock.patch.object(currency_check, "METADATA_DIR", Path(tmp)), \
                 mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
                result = currency_check_node(_state("1"))

        self.assertEqual(result["currency_labels"][0]["label"], "repealed")
        self.assertEqual(result["currency_labels"][0]["as_of_date"], "not-a-date")

    def test_no_citations_returns_empty_list(self):
        with mock.patch.dict(os.environ, {"CURRENCY_CHECK_ENABLED": "1"}):
            result = currency_check_node({"citations": [], "retrieved_chunks": []})

        self.assertEqual(result["currency_labels"], [])


if __name__ == "__main__":
    unittest.main()
