import pytest

from agent.citation_keys import (
    canonicalize_act_number,
    canonicalize_citation_key,
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
