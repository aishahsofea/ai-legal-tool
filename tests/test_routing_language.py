import os
from unittest.mock import patch

from agent import jev_client
from evals import routing_language as rl

_CASE = {"id": "c1", "language": "bm", "query_type": "topical", "query": "tolong semak seksyen 34",
         "history": [{"role": "user", "content": "hi"}]}


def _answers(language="bm", query_type="topical"):
    return {"query_type": {"choice": query_type}, "response_language": {"choice": language}}


def test_jev_source_reads_both_choices_and_tokens():
    def fake_classify(state, questions, *, timeout):
        jev_client.usage_observer.get()("m", 10, 3)
        assert set(questions) == {"query_type", "response_language"}
        assert "tolong semak seksyen 34" in state and "user: hi" in state
        return _answers("mixed")

    with patch.object(rl.jev_client, "classify", fake_classify):
        entry = rl.score(_CASE, "jev")
    assert (entry["language"], entry["query_type"]) == ("mixed", "topical")
    assert (entry["input_tokens"], entry["output_tokens"]) == (10, 3)
    assert entry["match"] is False


def test_jev_error_is_an_error_row_not_a_match():
    with patch.dict(os.environ, {}, clear=True):
        entry = rl.score(_CASE, "jev")
    assert "JevError" in entry["error"]
    assert entry["match"] is False


def test_fasttext_buckets_share_and_too_short_is_a_miss():
    for share, expected in ((0.9, "bm"), (0.5, "mixed"), (0.1, "en"), (None, None)):
        with patch.object(rl.language_id, "bm_share", return_value=share):
            assert rl._fasttext(_CASE)["language"] == expected


def test_summarise_reports_accuracy_by_source():
    entries = [
        {"id": "a", "source": "jev", "label": "bm", "label_type": "topical", "language": "bm",
         "query_type": "topical", "match": True, "latency_s": 1.0, "input_tokens": 5, "output_tokens": 1},
        {"id": "b", "source": "jev", "label": "en", "label_type": "topical", "language": "bm",
         "query_type": "clarify", "match": False, "latency_s": 3.0, "input_tokens": 5, "output_tokens": 1},
        {"id": "a", "source": "fasttext", "label": "bm", "language": None, "match": False, "latency_s": 0.01},
    ]
    report = rl.summarise(entries)
    assert report["jev"]["language_accuracy"] == 0.5
    assert report["jev"]["query_type_accuracy"] == 0.5
    assert report["jev"]["median_latency_s"] == 2.0
    assert report["jev"]["input_tokens"] == 10
    assert report["fasttext"]["language_accuracy"] == 0.0
