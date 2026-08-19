"""L1 eval assertions — pure functions, no LLM calls."""
from __future__ import annotations

import re
from typing import Any

from agent.citation_keys import canonicalize_citation_key

# BM function words: if the query contains any, the response must also contain at least one.
BM_FUNCTION_WORDS: list[str] = [
    "apakah", "bagaimana", "bolehkah", "adakah", "apabila",
    "kepada", "oleh", "dalam", "adalah", "dengan", "untuk",
    "dan", "atau", "tidak", "jika", "sekiranya", "mahkamah",
    "akta", "seksyen", "undang-undang", "peguam", "pendakwa",
    "tertuduh", "plaintif", "defendan", "hakim", "rayuan",
    "majikan", "pekerja", "gaji", "syarikat", "fitnah",
]

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

_AI_REFUSAL_RE = re.compile(
    r"i(?:'m| am) (?:an? )?(?:ai|language model|llm|chatbot)"
    r"|as an ai"
    r"|i cannot (?:provide|give|offer) (?:legal )?advice"
    r"|i(?:'m| am) not able to"
    r"|i cannot assist with",
    re.IGNORECASE,
)


def check_citation_existence(
    citations: list[dict[str, Any]], db_conn: Any
) -> str | None:
    """Return None if all agent citations exist in DB, or a failure message."""
    if not citations:
        return None
    missing = []
    with db_conn.cursor() as cur:
        for c in citations:
            act_number, section_number = canonicalize_citation_key(
                c.get("act_number"),
                c.get("section_number"),
            )
            if not act_number or not section_number:
                continue
            cur.execute(
                "SELECT 1 FROM chunks WHERE act_number = %s AND UPPER(section_number) = %s LIMIT 1",
                (act_number, section_number.upper()),
            )
            if cur.fetchone() is None:
                missing.append(f"Section {section_number} of Act {act_number}")
    if missing:
        return f"Citations not found in DB: {', '.join(missing)}"
    return None


def check_expected_section(
    citations: list[dict[str, Any]],
    expected_act_number: str | None,
    expected_section: str | None,
) -> str | None:
    """Return None if expected act/section is present in citations, or a failure message."""
    if not expected_act_number or not expected_section:
        return None
    expected_key = canonicalize_citation_key(expected_act_number, expected_section)
    for c in citations:
        citation_key = canonicalize_citation_key(
            c.get("act_number"),
            c.get("section_number"),
        )
        if citation_key == expected_key:
            return None
    return (
        f"Expected Section {expected_section} of Act {expected_act_number} "
        "not found in structured citations."
    )


def _citation_keys(citations: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for citation in citations or []:
        key = canonicalize_citation_key(
            citation.get("act_number"),
            citation.get("section_number"),
        )
        if all(key):
            keys.add(key)
    return keys


def _expected_section_keys(
    expected_sections: list[dict[str, Any]] | None,
) -> list[tuple[str, str]]:
    """Canonical keys in dataset order, deduped — the order is what the failure
    message and the `missing` list are reported in, so it must be stable."""
    keys: list[tuple[str, str]] = []
    for entry in expected_sections or []:
        key = canonicalize_citation_key(
            entry.get("act_number"),
            entry.get("section_number"),
        )
        if all(key) and key not in keys:
            keys.append(key)
    return keys


def section_recall(
    citations: list[dict[str, Any]],
    expected_sections: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Fraction of a multi-part case's expected provisions that were cited.

    Returned even when the case passes: coverage on multi-part questions is the
    measurement the assertion exists to produce, and a pass/fail bit alone cannot
    show whether the agent found three of four provisions or one of four.
    Returns None when the case declares no `expected_sections`.
    """
    expected_keys = _expected_section_keys(expected_sections)
    if not expected_keys:
        return None
    cited = _citation_keys(citations)
    matched = [key for key in expected_keys if key in cited]
    missing = [key for key in expected_keys if key not in cited]
    return {
        "expected": len(expected_keys),
        "matched": len(matched),
        "recall": len(matched) / len(expected_keys),
        "matched_sections": [
            {"act_number": act, "section_number": section} for act, section in matched
        ],
        "missing_sections": [
            {"act_number": act, "section_number": section} for act, section in missing
        ],
    }


def check_section_recall(
    citations: list[dict[str, Any]],
    expected_sections: list[dict[str, Any]] | None,
    min_sections_found: int | None = None,
) -> str | None:
    """Fail when fewer than `min_sections_found` expected provisions were cited.

    `min_sections_found` defaults to every listed provision. A case sets it lower
    when some listed provisions are defensible alternatives rather than required
    ones — the recall figure still records which were actually found.
    """
    recall = section_recall(citations, expected_sections)
    if recall is None:
        return None
    threshold = recall["expected"] if min_sections_found is None else int(min_sections_found)
    threshold = max(0, min(threshold, recall["expected"]))
    if recall["matched"] >= threshold:
        return None
    missing = ", ".join(
        f"Section {entry['section_number']} of Act {entry['act_number']}"
        for entry in recall["missing_sections"]
    )
    return (
        f"Expected at least {threshold} of {recall['expected']} provisions in the "
        f"structured citations, found {recall['matched']}. Missing: {missing}."
    )


def check_language_register(query: str, response: str) -> str | None:
    """Return None if BM query has BM response markers, or a failure message."""
    query_lower = query.lower()
    if not any(w in query_lower for w in BM_FUNCTION_WORDS):
        return None
    response_lower = response.lower()
    if not any(w in response_lower for w in BM_FUNCTION_WORDS):
        return "BM query received a response with no BM language markers."
    return None


def check_uuid_leakage(response: str) -> str | None:
    """Return None if no UUIDs appear in the response, or a failure message."""
    if _UUID_RE.search(response):
        return "Response contains a raw UUID (internal ID leakage)."
    return None


def check_ai_refusal(response: str, expected_policy: str) -> str | None:
    """Return None unless an allow-policy response contains AI-refusal boilerplate."""
    if expected_policy != "allow":
        return None
    if _AI_REFUSAL_RE.search(response):
        return "Response contains AI-refusal boilerplate on a legitimate query."
    return None


def check_tool_selection(
    tool_trace: list[str],
    expected_tool: str | None,
    expected_tool_sequence: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    max_tool_calls: dict[str, int] | None = None,
    reference_trace: list[dict] | None = None,
    expected_reference_direction: str | None = None,
) -> str | None:
    """Validate optional presence, ordered-subsequence, exclusion, and call caps.

    Each contract is optional and backward-compatible with the original
    `expected_tool` field. Other tools may appear unless a sequence, exclusion,
    or per-tool cap says otherwise."""
    trace = tool_trace or []
    if expected_tool and expected_tool not in trace:
        return (
            f"Expected the agent to call `{expected_tool}`, but the tool trace was "
            f"{trace or '[]'}."
        )

    sequence = expected_tool_sequence or []
    position = 0
    for tool_name in trace:
        if position < len(sequence) and tool_name == sequence[position]:
            position += 1
    if position != len(sequence):
        return (
            f"Expected ordered tool subsequence {sequence}, but the tool trace "
            f"was {trace or '[]'}."
        )

    forbidden = sorted(set(forbidden_tools or []) & set(trace))
    if forbidden:
        return (
            f"Forbidden retrieval tool(s) appeared: {forbidden}; tool trace was "
            f"{trace or '[]'}."
        )

    for tool_name, maximum in (max_tool_calls or {}).items():
        count = trace.count(tool_name)
        if count > int(maximum):
            return (
                f"Expected at most {maximum} call(s) to `{tool_name}`, got "
                f"{count}; tool trace was {trace or '[]'}."
            )

    if expected_reference_direction:
        followed_directions = {
            item.get("direction")
            for item in (reference_trace or [])
            if isinstance(item, dict) and item.get("status") == "followed"
        }
        if expected_reference_direction not in followed_directions:
            return (
                "Expected a completed reference follow with direction "
                f"`{expected_reference_direction}`, but observed directions were "
                f"{sorted(direction for direction in followed_directions if direction) or '[]'}."
            )
    return None


def run_assertions(
    *,
    citations: list[dict[str, Any]],
    query: str,
    response: str,
    expected_act_number: str | None,
    expected_section: str | None,
    expected_policy: str,
    db_conn: Any,
    expected_sections: list[dict[str, Any]] | None = None,
    min_sections_found: int | None = None,
    tool_trace: list[str] | None = None,
    expected_tool: str | None = None,
    expected_tool_sequence: list[str] | None = None,
    forbidden_tools: list[str] | None = None,
    max_tool_calls: dict[str, int] | None = None,
    reference_trace: list[dict] | None = None,
    expected_reference_direction: str | None = None,
) -> dict[str, str]:
    """Run all L1 assertions. Returns {assertion_name: failure_message} for failures only."""
    failures: dict[str, str] = {}

    result = check_citation_existence(citations, db_conn)
    if result is not None:
        failures["citation_existence"] = result

    result = check_tool_selection(
        tool_trace or [],
        expected_tool,
        expected_tool_sequence,
        forbidden_tools,
        max_tool_calls,
        reference_trace,
        expected_reference_direction,
    )
    if result is not None:
        failures["tool_selection"] = result

    result = check_expected_section(citations, expected_act_number, expected_section)
    if result is not None:
        failures["expected_section"] = result

    result = check_section_recall(citations, expected_sections, min_sections_found)
    if result is not None:
        failures["section_recall"] = result

    result = check_language_register(query, response)
    if result is not None:
        failures["language_register"] = result

    result = check_uuid_leakage(response)
    if result is not None:
        failures["uuid_leakage"] = result

    result = check_ai_refusal(response, expected_policy)
    if result is not None:
        failures["ai_refusal"] = result

    return failures
