import json
from pathlib import Path

from evals.coverage import case_section_pairs, required_section_pairs
from evals.run_evals import _load_dataset


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset.json"
CHUNKS_DIR = ROOT / "data" / "chunks" / "en"


def _multi_section_cases() -> list[dict]:
    return [case for case in _load_dataset(DATASET) if case["scenario"] == "multi_section"]


def test_every_multi_section_case_declares_a_scorable_expectation():
    cases = _multi_section_cases()
    assert cases
    for case in cases:
        expected = case.get("expected_sections")
        assert expected, case["id"]
        assert len(expected) >= 2, case["id"]
        # The scalar fields stay null: one Act/section cannot describe a
        # multi-part answer, and `check_expected_section` would score the case
        # as if it could.
        assert case.get("expected_act_number") is None, case["id"]
        assert case.get("expected_section") is None, case["id"]


def test_multi_section_cases_are_citation_applicable_so_coverage_requires_their_sections():
    for case in _multi_section_cases():
        assert case.get("citation_applicable") is True, case["id"]
        assert set(case_section_pairs(case)) <= required_section_pairs([case]), case["id"]


def test_min_sections_found_is_a_reachable_threshold():
    for case in _multi_section_cases():
        minimum = case.get("min_sections_found")
        assert minimum is not None, case["id"]
        assert 1 <= minimum <= len(case_section_pairs(case)), case["id"]


def test_every_citation_applicable_case_declares_at_least_one_expected_section():
    """Guards the exact bug this suite exists to catch: a citation_applicable case
    that declares zero sections (neither scalar fields nor expected_sections) would
    be silently unscored and unseeded, regardless of which `scenario` it's filed
    under -- unlike the other tests here, this one is not scoped to multi_section."""
    for case in _load_dataset(DATASET):
        if not case.get("citation_applicable"):
            continue
        assert case_section_pairs(case), case["id"]


def test_every_required_section_exists_in_the_chunk_corpus():
    """The eval seeder raises on a missing chunk, so a section listed here that
    the corpus does not carry breaks `seed_test_corpus` rather than failing one
    case."""
    missing = []
    for act_number, section_number in sorted(required_section_pairs(_load_dataset(DATASET))):
        path = CHUNKS_DIR / f"{act_number}.json"
        if not path.exists():
            missing.append((act_number, section_number))
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if section_number not in {row["section_number"] for row in rows}:
            missing.append((act_number, section_number))
    assert missing == []
