"""
Recall node — reads the Practitioner's Semantic Memory and projects it into
Working Memory (the answering prompt) for the current turn.

This is the *read* half of Semantic Memory (ADR 0010). From the cross-thread store
namespaced by (user_id, "semantic") it gathers two things and hands them to the
answering node as **soft context** — never authority, never citeable:
  - the practitioner's **profile** (identity/background, language, format style),
    fetched deterministically by kind so it is *always* present when stored rather
    than made to win a vector search against the current query (ADR 0012); and
  - **recurring topics** relevant to this query, retrieved by similarity.
The profile is listed first, then the query-ranked topics, deduped by key. The graph runs it in two places off the same functions: before the
synthesiser on the legal path, and before the conversational node on the
small-talk short-circuit, so remembered preferences inform both kinds of turn. The write path (agent/memory/extractor.py) populates the store in the
background after a turn; recall is a clean no-op while the store is still empty.

Contract (fail-open, dark by default — model on contextualize_node):
  - Gated behind SEMANTIC_MEMORY_RECALL: off (default) → no-op, behaviour is
    identical to before this node existed.
  - No user_id, no store, empty query, empty store, or any error → returns {}
    (Working Memory stays exactly as it would be without recall).
  - Reads user_id from config["configurable"] (ADR 0010), never from state.
  - Recalled text is a read-time projection: it is NOT appended to history
    (that reducer is an append-only legal audit artifact — ADR 0008) and it
    never feeds the router/escalation check (which stays on the raw query —
    ADR 0007). It only reaches the answering node (synthesiser or
    conversational) via state["recalled_memory"].

Sync (`recall_node`) and async (`arecall_node`) variants share their logic and
differ only in the store call — the sync path (invoke) drives an InMemoryStore /
PostgresStore, the async path (astream) drives an AsyncPostgresStore. Both are
registered on the graph via a single RunnableCallable so store injection works
in either execution mode.
"""
import asyncio
import json
import logging
import os

from langgraph.store.base import BaseStore, SearchItem

from agent.memory import stats
from agent.state import AgentState

logger = logging.getLogger(__name__)

_RECALL_LIMIT = 5

# The practitioner's own profile (identity, language, format style) is always relevant
# framing, so it is fetched deterministically by kind rather than made to win a vector
# similarity search against the current query — otherwise "what is my profession?" could
# rank below a closer-embedding topic and the profile would silently drop out of the
# top-_RECALL_LIMIT. Recurring topics stay query-ranked. Profiles are few (the pruner
# consolidates to one), so the cap is defensive.
_PROFILE_FILTER = {"kind": "PractitionerProfile"}
_PROFILE_LIMIT = 5


def _merge(profiles: list[SearchItem], relevant: list[SearchItem]) -> list[SearchItem]:
    """Profile(s) first (primary framing), then query-ranked items, deduped by key so a
    profile that also matched the similarity search is not listed twice."""
    seen: set = set()
    ordered: list[SearchItem] = []
    for item in (*profiles, *relevant):
        if item.key in seen:
            continue
        seen.add(item.key)
        ordered.append(item)
    return ordered

# Keep in-flight hit-recording tasks referenced so the loop can't GC them mid-flight.
_pending: set[asyncio.Task] = set()


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


def _render_fields(content: dict) -> str:
    """Flatten a structured memory into one "field: value; ..." line. Schema-agnostic
    so it survives new fields on the write-path schema (agent/memory/schemas.py)."""
    parts = []
    for key, val in content.items():
        if val in (None, "", [], {}):
            continue
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val if str(v).strip())
            if not val:
                continue
        parts.append(f"{key.replace('_', ' ')}: {val}")
    return "; ".join(parts)


def _fact_text(item: SearchItem) -> str:
    """Render one stored fact as a single readable line, tolerant of the value shape.

    The write path (LangMem) stores {"kind": ..., "content": {<fields>}}, so a dict
    `content` is flattened; text-bearing keys are used verbatim; anything else falls
    back to a JSON dump so a fact is never silently dropped.
    """
    value = item.value or {}
    content = value.get("content")
    if isinstance(content, dict):
        rendered = _render_fields(content)
        if rendered:
            return rendered
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


def _record_hits_sync(store: BaseStore, user_id: str, items: list[SearchItem]) -> None:
    """Retrieval-frequency signal (ADR 0010, Phase 4): the pruner scores importance on
    how often an item is recalled. Guarded so it can never affect recalled_memory."""
    try:
        stats.record_hits(store, user_id, [item.key for item in items])
    except Exception:
        logger.warning("recall hit recording failed; recalled memory unaffected", exc_info=True)


def _schedule_hits_async(store: BaseStore, user_id: str, items: list[SearchItem]) -> None:
    """Fire-and-forget the async hit recording so the read path is never slowed."""
    try:
        task = asyncio.create_task(stats.arecord_hits(store, user_id, [item.key for item in items]))
    except RuntimeError:  # no running loop
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def recall_node(state: AgentState, config, *, store: BaseStore | None = None) -> dict:
    plan = _plan(state, config, store)
    if plan is None:
        return {}
    user_id, query = plan
    try:
        ns = (user_id, "semantic")
        profiles = store.search(ns, filter=_PROFILE_FILTER, limit=_PROFILE_LIMIT)
        relevant = store.search(ns, query=query, limit=_RECALL_LIMIT)
        # Hits feed the pruner's importance score, which is a *relevance* signal — only the
        # query-ranked items earn one; the always-on profile must not skew it.
        if relevant:
            _record_hits_sync(store, user_id, relevant)
        return _to_update(_merge(profiles, relevant))
    except Exception:
        logger.warning("recall_node failed; continuing without Semantic Memory", exc_info=True)
        return {}


async def arecall_node(state: AgentState, config, *, store: BaseStore | None = None) -> dict:
    plan = _plan(state, config, store)
    if plan is None:
        return {}
    user_id, query = plan
    try:
        ns = (user_id, "semantic")
        profiles = await store.asearch(ns, filter=_PROFILE_FILTER, limit=_PROFILE_LIMIT)
        relevant = await store.asearch(ns, query=query, limit=_RECALL_LIMIT)
        # Only the query-ranked items earn an importance hit; the always-on profile must not skew it.
        if relevant:
            _schedule_hits_async(store, user_id, relevant)
        return _to_update(_merge(profiles, relevant))
    except Exception:
        logger.warning("recall_node failed; continuing without Semantic Memory", exc_info=True)
        return {}
