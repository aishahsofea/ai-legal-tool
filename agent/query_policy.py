"""Shared query lifecycle policy constants."""
from agent.state import Message

MAX_HISTORY_TURNS = 6
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


def trim_history(history: list[Message] | None, limit: int = MAX_HISTORY_TURNS) -> list[Message]:
    """Keep only the most recent turns before sending history to an LLM.

    The checkpoint stores all turns forever, so nodes must trim at read-time to
    bound token cost. Applied inside router_node and synthesiser_node.
    """
    if not history:
        return []
    return history[-limit:]
