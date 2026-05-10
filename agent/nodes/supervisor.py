"""
Supervisor node — rule-based policy enforcement before output.

Checks the draft response against 4 rules deterministically (no LLM call).
Rule-based checking is intentional: it is deterministic, testable, and cannot
hallucinate a false pass the way an LLM judge could.

Returns violations (list of strings). Empty list = pass.
"""
import re

from agent.state import AgentState

_ADVICE_RE = re.compile(
    r'\byou should\b|\byou must\b|\bin your case\b|\bi recommend\b'
    r'|\byou need to\b|\byou are advised\b',
    re.IGNORECASE,
)

_CITATION_RE = re.compile(
    r'section\s+\d+[A-Z]{0,2}\s+of\s+.{5,60}act',
    re.IGNORECASE,
)

_DISCLAIMER = "does not constitute legal advice"

_ESCALATION_RE = re.compile(
    r'\bmy client\b|\bam i liable\b|\bi have been charged\b',
    re.IGNORECASE,
)

ESCALATION_RESPONSE = (
    "This query involves a specific legal situation. "
    "I'm not able to provide advice on individual cases. "
    "Please consult a qualified Malaysian lawyer for assistance."
)


def supervisor_node(state: AgentState) -> dict:
    draft = state.get("draft_response", "")
    violations = []

    # Rule 1 — no specific-advice phrases
    if _ADVICE_RE.search(draft):
        violations.append("Contains specific advice phrases (you should / you must / I recommend).")

    # Rule 2 — at least one statute citation
    if not _CITATION_RE.search(draft):
        violations.append("No statute citation found. Every claim must cite 'Section X of [Act]'.")

    # Rule 3 — disclaimer present
    if _DISCLAIMER not in draft.lower():
        violations.append("Missing disclaimer that this is not legal advice.")

    # Rule 4 — escalation trigger in the response itself (shouldn't happen, but guard it)
    if _ESCALATION_RE.search(draft):
        return {
            "violations":     ["Escalation trigger detected in response."],
            "final_response": ESCALATION_RESPONSE,
        }

    # Always set final_response to the current draft so it is never empty.
    # The graph decides whether to retry (if violations) or output (if not).
    return {
        "violations":     violations,
        "final_response": draft,
    }
