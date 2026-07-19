from evals.coverage import (
    aggregate_scenarios,
    coverage_summary,
    missing_section_pairs,
    required_section_pairs,
    select_cases,
)
from evals.run_evals import serialize_case_result


def _case(
    case_id: str,
    *,
    scenario: str = "exact_match",
    category: str = "citation",
    policy: str = "allow",
    smoke: bool = False,
    act: str | None = "56",
    section: str | None = "90A",
    citation_applicable: bool = True,
) -> dict:
    return {
        "id": case_id,
        "category": category,
        "scenario": scenario,
        "query": f"Query for {case_id}",
        "expected_act_number": act,
        "expected_section": section,
        "citation_applicable": citation_applicable,
        "expected_policy": policy,
        "smoke": smoke,
    }


def test_coverage_summary_counts_cases_and_flags_only_values_below_thresholds():
    cases = [
        _case(f"exact-{index}", smoke=index == 0)
        for index in range(5)
    ] + [
        _case("mixed-allow", scenario="mixed_language", smoke=True),
        _case("mixed-block", scenario="mixed_language", policy="block"),
        _case("ambiguous", scenario="ambiguous", category="policy", policy="block"),
        _case("boundary", scenario="unsettled_law", category="policy", policy="block"),
        _case("multi", scenario="multi_section", category="policy", policy="block"),
    ]

    summary = coverage_summary(cases)

    assert summary["total_cases"] == 10
    assert summary["smoke_cases"] == 2
    assert summary["by_policy"] == {"allow": 6, "block": 4}
    assert summary["by_category"] == {"citation": 7, "policy": 3}
    assert summary["by_scenario"] == {
        "exact_match": 5,
        "mixed_language": 2,
        "ambiguous": 1,
        "unsettled_law": 1,
        "multi_section": 1,
    }
    assert {
        flag["scenario"] for flag in summary["gap_flags"]
        if flag["rule"] == "thin_scenario" and "scenario" in flag
    } == {
        "mixed_language",
        "ambiguous",
        "unsettled_law",
        "multi_section",
    }
    assert [
        flag for flag in summary["gap_flags"]
        if flag["rule"] == "thin_scenario" and "category" in flag
    ] == [{"rule": "thin_scenario", "category": "policy", "count": 3, "threshold": 5}]
    assert not any(flag["rule"] == "weak_boundary_coverage" for flag in summary["gap_flags"])
    assert {flag["scenario"] for flag in summary["gap_flags"] if flag["rule"] == "no_smoke_coverage"} == {
        "ambiguous",
        "unsettled_law",
        "multi_section",
    }


def test_coverage_summary_flags_block_share_below_but_not_equal_to_twenty_percent():
    below = [_case(f"allow-{index}") for index in range(5)] + [
        _case("block", policy="block"),
    ]
    boundary = [_case(f"allow-{index}") for index in range(4)] + [
        _case("block", policy="block"),
    ]

    below_flag = next(
        flag for flag in coverage_summary(below)["gap_flags"]
        if flag["rule"] == "weak_boundary_coverage"
    )
    assert below_flag == {
        "rule": "weak_boundary_coverage",
        "block_pct": 1 / 6,
        "threshold": 0.2,
    }
    assert not any(
        flag["rule"] == "weak_boundary_coverage"
        for flag in coverage_summary(boundary)["gap_flags"]
    )


def test_required_and_missing_sections_ignore_non_citation_cases_and_normalize_values():
    cases = [
        _case("needed", act="Act 56", section="Section 90a(1)"),
        _case("duplicate", act=" 56 ", section="90A"),
        _case("policy", act=None, section=None, citation_applicable=False),
    ]

    required = required_section_pairs(cases)
    missing = missing_section_pairs(required, {("56", "73A")})

    assert required == {("56", "90A")}
    assert missing == [{"act_number": "56", "section_number": "90A"}]


def test_select_cases_resolves_each_supported_dashboard_subset():
    cases = [
        _case("smoke-citation", smoke=True),
        _case("policy-case", category="policy", scenario="ambiguous", citation_applicable=False),
        _case("mixed-case", scenario="mixed_language"),
    ]

    assert [case["id"] for case in select_cases(cases, "all")] == [
        "smoke-citation", "policy-case", "mixed-case"
    ]
    assert [case["id"] for case in select_cases(cases, "smoke")] == ["smoke-citation"]
    assert [case["id"] for case in select_cases(cases, {"category": "policy"})] == ["policy-case"]
    assert [case["id"] for case in select_cases(cases, {"scenario": "mixed_language"})] == ["mixed-case"]
    assert [case["id"] for case in select_cases(cases, {"case_id": "policy-case"})] == ["policy-case"]


def test_select_cases_rejects_unknown_or_empty_subsets():
    cases = [_case("only")]

    for subset in ({"category": "missing"}, {"unknown": "value"}, "invalid"):
        try:
            select_cases(cases, subset)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected {subset!r} to be rejected")


def test_jsonl_serializer_exposes_the_documented_case_result_shape():
    result = {
        "case": _case("case-1", scenario="mixed_language", policy="block"),
        "agent": {
            "final_response": "The response",
            "citations": [{"act_number": "56", "section_number": "90A"}],
        },
        "l1_failures": {"expected_section": "Expected section was absent."},
        "judge": None,
        "elapsed_seconds": 1.25,
    }

    assert serialize_case_result(result) == {
        "id": "case-1",
        "category": "citation",
        "scenario": "mixed_language",
        "expected_policy": "block",
        "expected_act_number": "56",
        "expected_section": "90A",
        "l1_failures": ["expected_section"],
        "l1_failure_details": {"expected_section": "Expected section was absent."},
        "judge": None,
        "query": "Query for case-1",
        "response": "The response",
        "citations": [{"act_number": "56", "section_number": "90A"}],
        "elapsed_seconds": 1.25,
    }


def test_scenario_aggregation_requires_both_l1_and_judge_to_pass():
    results = [
        {"scenario": "exact_match", "l1_failures": [], "judge": {"passed": True}},
        {"scenario": "exact_match", "l1_failures": ["expected_section"], "judge": None},
        {"scenario": "mixed_language", "l1_failures": [], "judge": {"passed": False}},
    ]

    assert aggregate_scenarios(results) == {
        "exact_match": {"passed": 1, "total": 2, "rate": 0.5},
        "mixed_language": {"passed": 0, "total": 1, "rate": 0.0},
    }
