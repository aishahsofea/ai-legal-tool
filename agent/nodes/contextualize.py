"""
Contextualize node — rewrites an elliptical follow-up into a self-contained
**Standalone Query** used only for retrieval.

An elliptical follow-up like "what about criminal cases?" is meaningless to the
retriever in isolation: the raw string has no statute/topic context, so the
vector search retrieves garbage. This node resolves the follow-up against the
(disclaimer-free) conversation history into a query that stands on its own.

Contract:
  - First turn (empty history) skips the LLM entirely → standalone_query == "".
  - On any failure (exception or empty output) it fails open → "" — the retriever
    then falls back to the raw query, exactly as before this node existed.
  - state["query"] is NEVER overwritten; escalation re-checking stays on the raw
    query (see ADR 0007). Only standalone_query is produced.
"""
import logging
import os

from dotenv import load_dotenv
from pydantic import BaseModel

from agent.llm_factory import make_llm, system_content
from agent.query_policy import trim_history
from agent.state import AgentState

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = os.getenv("CONTEXTUALIZER_MODEL", "gpt-4.1-mini")
_llm = make_llm(_MODEL)


class _ContextualizeOutput(BaseModel):
    standalone_query: str


_structured_llm = _llm.with_structured_output(_ContextualizeOutput)

_SYSTEM = """You rewrite a follow-up question from a Malaysian legal research chat \
into a self-contained search query.

Using the conversation history, resolve references ("it", "that section", "what \
about...") so the query stands on its own without the history.

Rules:
- If the current query is already self-contained, return it UNCHANGED.
- Copy any section and Act tokens VERBATIM — "Section 90A" stays "Section 90A", \
"Evidence Act 1950" stays "Evidence Act 1950". Never renumber or reword them.
- Do NOT normalize language (keep Bahasa Malaysia as Bahasa Malaysia).
- Return only the rewritten search query in standalone_query — no commentary."""


def contextualize_node(state: AgentState) -> dict:
    history = trim_history(state.get("history", []))
    # Gate: first turn has no history to resolve against — skip the LLM call.
    if not history:
        return {"standalone_query": ""}

    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)

    try:
        result: _ContextualizeOutput = _structured_llm.invoke([
            {"role": "system", "content": system_content(_SYSTEM, _MODEL)},
            {"role": "user", "content": f"Conversation history:\n{history_text}\n\nFollow-up query:\n{state['query']}"},
        ])
        standalone = (result.standalone_query or "").strip()
        if not standalone:
            return {"standalone_query": ""}
        return {"standalone_query": standalone}
    except Exception:
        # Fail open: the retriever falls back to the raw query.
        logger.warning("contextualize_node failed; falling back to raw query", exc_info=True)
        return {"standalone_query": ""}
