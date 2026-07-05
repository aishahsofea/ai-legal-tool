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

_DISCLAIMER = "does not constitute legal advice"

_ESCALATION_RE = re.compile(
    r'\bmy client\b|\bam i liable\b|\bi have been charged\b',
    re.IGNORECASE,
)

ESCALATION_RESPONSE = (
    "This sounds like it's about a specific situation rather than general research, "
    "so I'll hold off — advising on individual cases really needs a qualified Malaysian "
    "lawyer who can look at the full picture. If it helps, I'm happy to pull up the "
    "relevant legislation on the underlying legal question."
)


def supervisor_node(state: AgentState) -> dict:
    draft = state.get("draft_response", "")
    violations = list(state.get("violations", []))

    # Rule 1 — no specific-advice phrases
    if _ADVICE_RE.search(draft):
        violations.append("Contains specific advice phrases (you should / you must / I recommend).")

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
