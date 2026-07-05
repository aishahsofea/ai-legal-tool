"""Retrieval-frequency signal for Semantic Memory pruning (ADR 0010, Phase 4).

The `recall` node records a hit on every item it surfaces; the pruner reads these
back as the *importance* half of its importance+recency eviction score. Hits live in
a side namespace ``(user_id, "semantic_meta")`` keyed by the content item's key and
written with ``index=False`` so they are never embedded or returned by recall's
vector search.

Kept deliberately separate from the content item: recording a hit must never touch
the item's ``updated_at``, so recency stays the content-write time and importance is
the recall count. Every helper here is fail-open — a stats error must never affect a
delivered turn or a pruning pass.
"""
import logging
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

logger = logging.getLogger(__name__)

_META = "semantic_meta"
_LOAD_LIMIT = 1000


def meta_namespace(user_id: str) -> tuple[str, str]:
    return (user_id, _META)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bumped(existing: dict | None) -> dict:
    count = (existing or {}).get("recall_count", 0)
    return {"recall_count": count + 1, "last_recalled": _now()}


def record_hits(store: BaseStore, user_id: str, keys: list[str]) -> None:
    """Sync: bump the recall counter for each surfaced item key. Fail-open per key."""
    ns = meta_namespace(user_id)
    for key in keys:
        try:
            existing = store.get(ns, key)
            store.put(ns, key, _bumped(existing.value if existing else None), index=False)
        except Exception:
            logger.warning("recall hit recording failed; recalled memory unaffected", exc_info=True)


async def arecord_hits(store: BaseStore, user_id: str, keys: list[str]) -> None:
    """Async variant of record_hits, for the AsyncPostgresStore path."""
    ns = meta_namespace(user_id)
    for key in keys:
        try:
            existing = await store.aget(ns, key)
            await store.aput(ns, key, _bumped(existing.value if existing else None), index=False)
        except Exception:
            logger.warning("recall hit recording failed; recalled memory unaffected", exc_info=True)


async def aload_hits(store: BaseStore, user_id: str) -> dict[str, dict]:
    """Read all recall stats for a user as ``{item_key: {"recall_count", "last_recalled"}}``."""
    ns = meta_namespace(user_id)
    try:
        items = await store.asearch(ns, limit=_LOAD_LIMIT)
    except Exception:
        logger.warning("recall stats load failed; pruning treats all items as un-recalled", exc_info=True)
        return {}
    return {item.key: (item.value or {}) for item in items}


async def adelete_hits(store: BaseStore, user_id: str, keys) -> None:
    """Drop stats rows for evicted/consolidated items so they don't outlive their content."""
    ns = meta_namespace(user_id)
    for key in keys:
        try:
            await store.adelete(ns, key)
        except Exception:
            logger.warning("recall stats delete failed; orphan stat row left behind", exc_info=True)
