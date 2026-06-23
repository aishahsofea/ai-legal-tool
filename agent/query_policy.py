"""Shared query lifecycle policy constants."""
from agent.state import Message

MAX_HISTORY_TURNS = 3
MAX_RETRIES = 1
FINAL_FAILURE_RESPONSE = (
    "I'm sorry, but I couldn't produce a compliant legal research answer for this query. "
    "Please rephrase the research question or consult a qualified Malaysian lawyer."
)

# Disclaimer suffixes appended by the synthesiser. Kept here as the single source
# of truth so strip_disclaimer removes exactly what was appended (no fuzzy matching).
_DISCLAIMER_EN = (
    "\n\n---\n"
    "*This information is for legal research only and does not constitute legal advice. "
    "Please consult a qualified Malaysian lawyer for advice on your specific situation.*"
)
_DISCLAIMER_BM = (
    "\n\n---\n"
    "*Maklumat ini adalah untuk tujuan penyelidikan undang-undang sahaja dan tidak merupakan "
    "nasihat undang-undang. Sila rujuk peguam Malaysia yang berkelayakan untuk nasihat berhubung "
    "situasi khusus anda.*"
)


def strip_disclaimer(text: str) -> str:
    """Remove the appended disclaimer suffix from an assistant response.

    Stored history should be disclaimer-free so later nodes (router, synthesiser,
    contextualize) don't re-read repeated boilerplate. We strip the exact suffix
    the synthesiser appended; text without a trailing disclaimer (escalation,
    fail-closed) is returned unchanged.
    """
    for disclaimer in (_DISCLAIMER_EN, _DISCLAIMER_BM):
        if text.endswith(disclaimer):
            return text[: -len(disclaimer)]
    return text


def delivered_response(state) -> str:
    """The response the user actually receives: the safe fallback when violations
    remain, otherwise the final draft. Single source of truth shared by the graph
    (history recording) and the query lifecycle (user-facing return).

    Does NOT strip the disclaimer — that stays a history-only concern.
    """
    if state.get("violations"):
        return FINAL_FAILURE_RESPONSE
    return state.get("final_response") or state.get("draft_response") or ""


def trim_history(history: list[Message] | None, max_turns: int = MAX_HISTORY_TURNS) -> list[Message]:
    """Keep only the most recent turns before sending history to an LLM.

    The checkpoint stores all turns forever, so nodes must trim at read-time to
    bound token cost. Applied inside the router, contextualize, and synthesiser nodes.

    Slices in whole *turns* (user+assistant pairs), not raw messages: the limit is
    honest about its unit, and a turn-aligned slice can never begin on a dangling
    assistant reply with no preceding question.
    """
    if not history:
        return []
    trimmed = history[-(max_turns * 2):]
    # Self-protecting boundary: if the slice begins on an assistant reply (only
    # possible from a malformed, non-paired history), drop it so the LLM never
    # receives a dangling reply with no preceding question.
    if trimmed[0]["role"] != "user":
        trimmed = trimmed[1:]
    return trimmed
