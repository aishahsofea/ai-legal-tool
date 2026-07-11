"""L1 eval assertions — pure functions, no LLM calls."""
from __future__ import annotations

import re
from typing import Any

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
            act_number = c.get("act_number", "")
            section_number = c.get("section_number", "")
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
    for c in citations:
        if (
            str(c.get("act_number", "")) == str(expected_act_number)
            and c.get("section_number", "").upper() == expected_section.upper()
        ):
            return None
    return (
        f"Expected Section {expected_section} of Act {expected_act_number} "
        "not found in structured citations."
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
) -> str | None:
    """Return None if the agent called the expected retrieval tool, else a message.

    Applies only when a case declares `expected_tool` (agentic retrieval). Passes
    as long as the expected tool appears somewhere in the trace — the agent may
    also call others (e.g. a fallback search after an exact-lookup miss)."""
    if not expected_tool:
        return None
    if expected_tool in (tool_trace or []):
        return None
    return (
        f"Expected the agent to call `{expected_tool}`, but the tool trace was "
        f"{tool_trace or '[]'}."
    )


def run_assertions(
    *,
    citations: list[dict[str, Any]],
    query: str,
    response: str,
    expected_act_number: str | None,
    expected_section: str | None,
    expected_policy: str,
    db_conn: Any,
    tool_trace: list[str] | None = None,
    expected_tool: str | None = None,
) -> dict[str, str]:
    """Run all L1 assertions. Returns {assertion_name: failure_message} for failures only."""
    failures: dict[str, str] = {}

    result = check_citation_existence(citations, db_conn)
    if result is not None:
        failures["citation_existence"] = result

    result = check_tool_selection(tool_trace or [], expected_tool)
    if result is not None:
        failures["tool_selection"] = result

    result = check_expected_section(citations, expected_act_number, expected_section)
    if result is not None:
        failures["expected_section"] = result

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
