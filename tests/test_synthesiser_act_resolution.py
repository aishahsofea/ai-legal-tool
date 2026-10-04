from agent.nodes.synthesiser import _resolve_act_number

CHUNKS = [
    {"act_number": "56", "act_title": "Evidence Act 1950"},
    {"act_number": "593", "act_title": "Criminal Procedure Code"},
]


def test_bare_and_prefixed_numbers_pass_through():
    assert _resolve_act_number("56", CHUNKS) == "56"
    assert _resolve_act_number("Act 56", CHUNKS) == "Act 56"


def test_echoed_title_resolves_to_number():
    assert _resolve_act_number("Evidence Act 1950", CHUNKS) == "56"
    assert _resolve_act_number("EVIDENCE ACT 1950 (Act 56)", CHUNKS) == "56"


def test_title_marker_and_case_are_ignored():
    chunks = [{"act_number": "777", "act_title": "*COMPANIES ACT 2016"}]
    assert _resolve_act_number("Companies Act 2016 (Act 777)", chunks) == "777"


def test_unretrieved_act_stays_unresolved():
    assert _resolve_act_number("Penal Code", CHUNKS) == "Penal Code"


def test_ambiguous_title_stays_unresolved():
    twins = [
        {"act_number": "1", "act_title": "Evidence Act"},
        {"act_number": "2", "act_title": "Evidence Act"},
    ]
    assert _resolve_act_number("Evidence Act", twins) == "Evidence Act"
