import pytest

from scraper.act_paths import act_number_from_stem, metadata_path, metadata_stem


@pytest.mark.parametrize("act_number", ["1", "265", "A1392", "406 (Revised)", "91 (revised)", "NO. 26 OF 1963"])
def test_act_numbers_that_are_already_safe_filenames_are_unchanged(act_number):
    """Every metadata file on disk today was written as the bare Act number.
    Escaping one of those would orphan the file it already has."""
    assert metadata_stem(act_number) == act_number


@pytest.mark.parametrize("act_number", ["49/1965", "31/1961", "26/1947"])
def test_a_separator_never_survives_into_a_path(act_number):
    path = metadata_path("data/acts_metadata", act_number)

    assert path.parent.as_posix() == "data/acts_metadata"
    assert "/" not in path.name
    assert "\\" not in path.name


@pytest.mark.parametrize(
    "act_number",
    ["1", "49/1965", "406 (Revised)", "NO. 26 OF 1963", r"a\b", "100%", "already%2Fescaped"],
)
def test_the_mapping_round_trips(act_number):
    """An Act number that already looks escaped must not decode to a different
    Act — that is how two Acts would end up sharing one metadata file."""
    assert act_number_from_stem(metadata_stem(act_number)) == act_number


def test_debug_dump_shares_the_stem_with_the_metadata_file():
    assert metadata_path("out", "49/1965", "_debug.html").name == "49%2F1965_debug.html"
    assert metadata_path("out", "49/1965").name == "49%2F1965.json"


@pytest.mark.parametrize("act_number", ["", "   ", None])
def test_an_empty_act_number_has_no_file(act_number):
    with pytest.raises(ValueError):
        metadata_stem(act_number)
