from evals.routing_summary import miss_direction, summarise


def _entry(case, label, got, *, repeat=0, lang="en", got_lang=None, tags=(), **extra):
    return {
        "id": case, "case": case, "repeat": repeat, "tags": list(tags),
        "label_type": label, "label_language": lang,
        "query_type": got, "response_language": got_lang or lang,
        "type_match": label == got, "language_match": (got_lang or lang) == lang,
        "miss_direction": miss_direction(label, got), **extra,
    }


def _error(case, label="topical", repeat=0, text="boom"):
    return {"id": case, "case": case, "repeat": repeat, "label_type": label,
            "label_language": "en", "tags": [], "error": text}


def test_summary_miss_direction_buckets():
    assert miss_direction("topical", "topical") is None
    assert miss_direction("clarify", "statute_lookup") == "clarify_to_legal"
    assert miss_direction("provision_extraction", "clarify") == "legal_to_clarify"
    assert miss_direction("topical", "conversational") == "legal_to_conversational"
    assert miss_direction("conversational", "clarify") == "other"
    assert miss_direction("clarify", "conversational") == "other"
    assert miss_direction("statute_lookup", "topical") == "other"


def test_summary_counts_and_groups():
    results = [
        _entry("a", "topical", "topical", tags=["tie_break"]),
        _entry("b", "clarify", "topical", lang="ms", got_lang="en", tags=["clarify_boundary"]),
        _entry("c", "topical", "clarify"),
        _entry("d", "topical", "conversational"),
    ]
    s = summarise(results)
    assert (s["total_cases"], s["total_runs"], s["errors"]) == (4, 4, 0)
    assert s["query_type_accuracy"] == 0.25
    assert s["language_accuracy"] == 0.75
    assert s["confusion"]["topical"] == {"topical": 1, "clarify": 1, "conversational": 1}
    assert s["miss_directions"] == {
        "clarify_to_legal": 1, "legal_to_clarify": 1, "legal_to_conversational": 1, "other": 0}
    assert set(s["by_tag"]) == {"tie_break", "clarify_boundary"}
    assert s["by_tag"]["tie_break"]["type_accuracy"] == 1.0
    assert s["by_language"]["ms"] == {"n": 1, "type_accuracy": 0.0, "language_accuracy": 0.0}
    assert s["by_query_type"]["topical"]["n"] == 3
    assert s["agreement"] is None


def test_summary_error_excluded_from_accuracy():
    s = summarise([_entry("a", "topical", "topical"), _error("b"), _error("c")])
    assert s["errors"] == 2
    assert s["by_error"] == {"boom": 2}
    assert s["query_type_accuracy"] == 1.0
    assert s["by_query_type"]["topical"]["n"] == 1


def test_summary_agreement_over_repeats():
    results = []
    for repeat, got in enumerate(["topical", "topical", "clarify"]):
        results.append(_entry("flaky", "topical", got, repeat=repeat))
        results.append(_entry("steady", "topical", "topical", repeat=repeat))
    s = summarise(results)
    assert s["agreement"] == {"cases": 2, "agree": 1, "rate": 0.5}


def test_summary_counts_route_paths():
    results = [
        _entry("a", "topical", "topical", route_path="jev"),
        _entry("b", "topical", "topical", route_path="jev"),
        _entry("c", "topical", "topical", route_path="fallback"),
        _entry("d", "topical", "topical"),
        _error("e"),
    ]
    assert summarise(results)["by_path"] == {"jev": 2, "llm": 1, "fallback": 1}


def test_summary_empty_and_all_error_no_zero_division():
    for results in ([], [_error("a")]):
        s = summarise(results)
        assert s["query_type_accuracy"] == 0.0
        assert s["language_accuracy"] == 0.0
        assert s["by_tag"] == {}


# --- runner ---------------------------------------------------------------

import json
import itertools

import pytest

from evals import run_routing
from evals.run_routing import score_case, select_routing_cases

_DATASET = json.loads(run_routing.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))["cases"]


def _fake(query_type="statute_lookup", language=None):
    return lambda case: {"query_type": query_type, "response_language": language or case["language"]}


def _run(monkeypatch, tmp_path, fake, *argv):
    monkeypatch.setattr(run_routing, "_route", fake)
    out = tmp_path / "out.json"
    code = run_routing.main(["--output", str(out), *argv])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_always_statute_lookup_scores_35_of_99(monkeypatch, tmp_path):
    code, data = _run(monkeypatch, tmp_path, _fake())
    assert code == 0
    s = data["summary"]
    assert s["total_cases"] == 99
    assert round(s["query_type_accuracy"] * 99) == 35
    assert s["language_accuracy"] == 1.0


def test_raising_case_is_error_exit_1_and_output_written(monkeypatch, tmp_path):
    def fake(case):
        if case["id"] == _DATASET[0]["id"]:
            raise RuntimeError("timeout")
        return _fake()(case)

    code, data = _run(monkeypatch, tmp_path, fake)
    assert code == 1
    assert data["summary"]["errors"] == 1
    assert data["summary"]["by_error"] == {"RuntimeError: timeout": 1}


def test_score_case_records_route_path():
    assert score_case(_DATASET[0], _fake(), 0)["route_path"] == "llm"
    jev = lambda case: {**_fake()(case), "route_path": "jev"}
    assert score_case(_DATASET[0], jev, 0)["route_path"] == "jev"


def test_escalate_is_error_not_miss():
    entry = score_case(_DATASET[0], _fake("escalate"), 0)
    assert "escalation regex matched" in entry["error"]
    assert "miss_direction" not in entry


def test_repeats_report_agreement_below_one(monkeypatch, tmp_path):
    flip = itertools.count()

    def fake(case):
        if case["id"] == _DATASET[0]["id"]:
            return _fake("topical" if next(flip) % 2 else "statute_lookup")(case)
        return _fake()(case)

    _, data = _run(monkeypatch, tmp_path, fake, "--repeats", "3", "--limit", "5")
    assert data["summary"]["total_runs"] == 15
    assert data["summary"]["agreement"]["rate"] < 1


def test_tag_selection_is_or_and_repeatable():
    assert len(select_routing_cases(_DATASET, tags=["tie_break", "clarify_boundary"])) == 19
    assert len(select_routing_cases(_DATASET, tags=["tie_break,clarify_boundary"])) == 19


def test_other_selectors():
    assert len(select_routing_cases(_DATASET, query_type="clarify")) == 13
    assert {c["language"] for c in select_routing_cases(_DATASET, language="bm")} == {"bm"}
    assert len(select_routing_cases(_DATASET, limit=4)) == 4
    ids = f"{_DATASET[1]['id']},{_DATASET[2]['id']}"
    assert [c["id"] for c in select_routing_cases(_DATASET, case_ids=ids)] == ids.split(",")
    with pytest.raises(ValueError, match="Unknown case ids"):
        select_routing_cases(_DATASET, case_ids="nope")
    with pytest.raises(ValueError, match="no cases"):
        select_routing_cases(_DATASET, language="bm", query_type="clarify", tags=["history"])
