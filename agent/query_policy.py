"""Shared query lifecycle policy constants."""
from agent.state import Message

MAX_HISTORY_TURNS = 6
MAX_RETRIES = 1
FINAL_FAILURE_RESPONSE = (
    "I'm sorry, but I couldn't produce a compliant legal research answer for this query. "
    "Please rephrase the research question or consult a qualified Malaysian lawyer."
)


def trim_history(history: list[Message] | None, limit: int = MAX_HISTORY_TURNS) -> list[Message]:
    """Keep only the most recent turns before sending history to an LLM.

    The checkpoint stores all turns forever, so nodes must trim at read-time to
    bound token cost. Applied inside router_node and synthesiser_node.
    """
    if not history:
        return []
    return history[-limit:]
