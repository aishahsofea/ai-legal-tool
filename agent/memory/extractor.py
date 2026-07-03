"""Background extraction — the write half of Semantic Memory (ADR 0010).

After a legal turn is delivered, extract durable practitioner facts (preferences +
recurring topics) and upsert them into the cross-thread `(user_id, "semantic")`
store via LangMem. Gated behind SEMANTIC_MEMORY_EXTRACT (default off), runs off the
hot path, and is fail-open — mirroring the recall node's posture. The `recall` node
reads back what this writes.
"""
import asyncio
import logging
import os

from langgraph.store.base import BaseStore

from agent.llm_factory import make_llm
from agent.memory.schemas import PractitionerProfile, RecurringTopic

logger = logging.getLogger(__name__)

# Sentinel a client with no persisted UUID sends; scoping memory to it would blend browsers.
_ANONYMOUS = "anonymous"

_DEFAULT_MODEL = "gpt-4.1-mini"

_EXTRACTION_INSTRUCTIONS = """You maintain durable Semantic Memory about a legal Practitioner across their research threads.

Extract ONLY stable facts about how this practitioner likes to work and what they research:
- Response-language preference (English, Bahasa Malaysia, or mixed).
- Citation / formatting style preferences.
- Practice-area focus (e.g. employment, criminal, corporate).
- Malaysian Acts they reference frequently.
- Recurring research topics they return to.

NEVER store confidential client or matter facts: client names, party names, case
specifics, dates, amounts, or anything tied to a particular dispute or transaction.
These carry retention and privilege obligations and must not enter durable memory.
When in doubt, do not store it. If the turn contains no durable preference or
recurring topic, extract nothing.

Reconcile with existing memories: update a preference in place when it changes,
and add a recurring topic only when it is genuinely new."""


def _enabled() -> bool:
    return os.getenv("SEMANTIC_MEMORY_EXTRACT", "").strip().lower() == "on"


def _model_name() -> str:
    return os.getenv("MEMORY_EXTRACT_MODEL", _DEFAULT_MODEL)


# One manager per store instance (the store is a startup singleton; id() keys let tests differ).
_managers: dict[int, object] = {}


def _manager(store: BaseStore):
    key = id(store)
    mgr = _managers.get(key)
    if mgr is None:
        # Lazy import so the flag-off path builds no LLM client.
        from langmem import create_memory_store_manager

        mgr = create_memory_store_manager(
            make_llm(_model_name()),
            schemas=[PractitionerProfile, RecurringTopic],
            instructions=_EXTRACTION_INSTRUCTIONS,
            enable_inserts=True,   # collection strategy; over-update accepted (ADR 0010)
            enable_deletes=False,  # pruning is a later phase
            namespace=("{user_id}", "semantic"),  # resolves to the namespace recall reads
            store=store,
        )
        _managers[key] = mgr
    return mgr


async def extract_memory(
    store: BaseStore | None, user_id: str | None, query: str, response: str
) -> None:
    """Extract + upsert this turn's durable facts. Fail-open.

    Feeds only the delivered turn; LangMem reconciles against existing memories, so
    recurrence is captured without re-processing the whole thread.
    """
    if not _enabled():
        return
    if store is None or not user_id or user_id == _ANONYMOUS:
        return
    query = (query or "").strip()
    response = (response or "").strip()
    if not query or not response:
        return
    try:
        await _manager(store).ainvoke(
            {"messages": [
                {"role": "user", "content": query},
                {"role": "assistant", "content": response},
            ]},
            config={"configurable": {"user_id": user_id}},
        )
    except Exception:
        logger.warning("semantic memory extraction failed; turn unaffected", exc_info=True)


# Keep in-flight tasks referenced so the loop can't GC them once the request returns.
_pending: set[asyncio.Task] = set()


def schedule_extraction(
    store: BaseStore | None, user_id: str | None, query: str, response: str
) -> None:
    """Fire-and-forget the write path after the response is delivered; all gating
    and error handling live in extract_memory."""
    try:
        task = asyncio.create_task(extract_memory(store, user_id, query, response))
    except RuntimeError:  # no running loop
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)
