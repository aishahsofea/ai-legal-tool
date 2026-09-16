import pytest

from agent.citation_keys import (
    canonicalize_act_number,
    canonicalize_citation_key,
    canonicalize_path,
    canonicalize_section_number,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (559, "559"),
        (" 559 ", "559"),
        ("Act 559", "559"),
        ("ACT No. 559", "559"),
        ("Akta 559", "559"),
        ("fc", "FC"),
        (None, ""),
    ],
)
def test_canonicalize_act_number(value, expected):
    assert canonicalize_act_number(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("90a", "90A"),
        ("Section 90A(1)", "90A"),
        ("seksyen 90a(1)(b)", "90A"),
        ("s. 60k", "60K"),
        ("Article 5", "5"),
        ("Perkara 5(1)", "5"),
        (None, ""),
        ("not a section", ""),
    ],
)
def test_canonicalize_section_number(value, expected):
    assert canonicalize_section_number(value) == expected


def test_canonicalize_citation_key_normalizes_both_identifiers():
    assert canonicalize_citation_key(" Act 559 ", "Section 19(1)") == ("559", "19")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("s.90A", "s.90A"),
        ("S.1", "s.1"),
        ("sched.2", "sched.2"),
        ("sched.2/para.1", "sched.2/para.1"),
        ("SCHED.1/ART.20", "sched.1/art.20"),
        ("sched.1 / para.1", "sched.1/para.1"),
        ("", ""),
        (None, ""),
        ("90A", ""),
        ("sched.2/foo.1", ""),
        ("not a path", ""),
    ],
)
def test_canonicalize_path(value, expected):
    assert canonicalize_path(value) == expected


def test_canonicalize_citation_key_prefers_section_number_over_path():
    # A body chunk always has a real section_number - the LLM was shown it (not
    # the path) and echoes it back, so it must be what the comparison key uses
    # even when a path is also available on the chunk side.
    assert canonicalize_citation_key("56", "90A", "s.90A") == ("56", "90A")


def test_canonicalize_citation_key_falls_back_to_path_for_a_schedule_chunk():
    # A schedule chunk's section_number is genuinely "" (ADR 0018) - only then
    # does the explicit path argument decide the key.
    assert canonicalize_citation_key("56", "", "sched.2/para.1") == ("56", "sched.2/para.1")
    assert canonicalize_citation_key("56", "") == ("56", "")


def test_canonicalize_citation_key_two_arg_call_still_resolves_an_echoed_path():
    # An LLM/judge-echoed field has no separate path argument - a path-shaped
    # string it echoes back arrives in the section_number slot instead, and
    # still has to resolve, since canonicalize_section_number rejects it.
    assert canonicalize_citation_key("56", "sched.2/para.1") == ("56", "sched.2/para.1")
