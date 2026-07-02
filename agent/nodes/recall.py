"""
Recall node — reads the Practitioner's Semantic Memory and projects it into
Working Memory (the synthesiser prompt) for the current turn.

This is the *read* half of Semantic Memory (ADR 0010). It searches the
cross-thread store namespaced by (user_id, "semantic") for facts relevant to the
query being answered and hands them to the synthesiser as **soft context** —
known practitioner preferences and recurring topics, never authority and never
citeable. Phase 3 writes to the store; until then it is empty and recall is a
clean no-op.

Contract (fail-open, dark by default — model on contextualize_node):
  - Gated behind SEMANTIC_MEMORY_RECALL: off (default) → no-op, behaviour is
    identical to before this node existed.
  - No user_id, no store, empty query, empty store, or any error → returns {}
    (Working Memory stays exactly as it would be without recall).
  - Reads user_id from config["configurable"] (ADR 0010), never from state.
  - Recalled text is a read-time projection: it is NOT appended to history
    (that reducer is an append-only legal audit artifact — ADR 0008) and it
    never feeds the router/escalation check (which stays on the raw query —
    ADR 0007). It only reaches the synthesiser via state["recalled_memory"].

Sync (`recall_node`) and async (`arecall_node`) variants share their logic and
differ only in the store call — the sync path (invoke) drives an InMemoryStore /
PostgresStore, the async path (astream) drives an AsyncPostgresStore. Both are
registered on the graph via a single RunnableCallable so store injection works
in either execution mode.
"""
import json
import logging
import os

from langgraph.store.base import BaseStore, SearchItem

from agent.state import AgentState

logger = logging.getLogger(__name__)

_RECALL_LIMIT = 5


def _enabled() -> bool:
    return os.getenv("SEMANTIC_MEMORY_RECALL", "").strip().lower() == "on"


def _user_id(config) -> str | None:
    return (config.get("configurable") or {}).get("user_id")


def _recall_query(state: AgentState) -> str:
    # Prefer the history-resolved Standalone Query when contextualize produced one,
    # so an elliptical follow-up still recalls the right facts; otherwise the raw query.
    return (state.get("standalone_query") or state.get("query") or "").strip()


def _plan(state: AgentState, config, store: BaseStore | None) -> tuple[str, str] | None:
    """Shared pre-flight for both variants. Returns (user_id, query) or None (no-op)."""
    if not _enabled():
        return None
    user_id = _user_id(config)
    if not user_id or store is None:
        return None
    query = _recall_query(state)
    if not query:
        return None
    return user_id, query


def _fact_text(item: SearchItem) -> str:
    """Render one stored fact as a single readable line.

    Tolerant of the value shape: Phase 3 fixes the schema, but recall must not
    assume it. Common text-bearing keys are used verbatim; anything else falls
    back to a compact JSON dump so a fact is never silently dropped.
    """
    value = item.value or {}
    for key in ("text", "fact", "content", "preference", "topic", "summary"):
        val = value.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_update(items: list[SearchItem]) -> dict:
    lines = [line for item in items if (line := _fact_text(item))]
    if not lines:
        return {}
    return {"recalled_memory": "\n".join(f"- {line}" for line in lines)}


def recall_node(state: AgentState, config, *, store: BaseStore | None = None) -> dict:
    plan = _plan(state, config, store)
    if plan is None:
        return {}
    user_id, query = plan
    try:
        items = store.search((user_id, "semantic"), query=query, limit=_RECALL_LIMIT)
        return _to_update(items)
    except Exception:
        logger.warning("recall_node failed; continuing without Semantic Memory", exc_info=True)
        return {}


async def arecall_node(state: AgentState, config, *, store: BaseStore | None = None) -> dict:
    plan = _plan(state, config, store)
    if plan is None:
        return {}
    user_id, query = plan
    try:
        items = await store.asearch((user_id, "semantic"), query=query, limit=_RECALL_LIMIT)
        return _to_update(items)
    except Exception:
        logger.warning("recall_node failed; continuing without Semantic Memory", exc_info=True)
        return {}
