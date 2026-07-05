"""Pruning + consolidation — the maintenance half of Semantic Memory (ADR 0010, Phase 4).

Keeps ``(user_id, "semantic")`` bounded and high quality *without* TTL: collapse
duplicate ``PractitionerProfile`` items into one, consolidate near-duplicate
``RecurringTopic`` items, and evict low-value topics by an **importance + recency**
score — retrieval frequency (agent/memory/stats.py) weighted against the item's
``updated_at``. Age is one input, never the policy: a stale-but-frequently-recalled
fact must outlive recent chatter.

Posture mirrors the extractor: gated behind ``SEMANTIC_MEMORY_PRUNE`` (default off),
runs off the hot path, fail-open. Conservative because deletion is irreversible —
never deletes the sole profile and never empties a namespace. Deletion lives here,
not in the extractor (which stays ``enable_deletes=False``): pruning owns it as a
deliberate, separate pass.
"""
import asyncio
import logging
import math
import os
from datetime import datetime, timezone

from langgraph.store.base import BaseStore, SearchItem

from agent.memory import stats

logger = logging.getLogger(__name__)

# Sentinel a client with no persisted UUID sends; pruning it would blend browsers.
_ANONYMOUS = "anonymous"

_PROFILE = "PractitionerProfile"
_TOPIC = "RecurringTopic"

# Tunable, eval-validated (evals/semantic_memory.py). Dedupe does the heavy lifting;
# the cap is a generous backstop, not the main lever.
_TOPIC_CAP = 30            # keep at most this many topics after consolidation
_TRIGGER_MARGIN = 10       # only run a full pass once the namespace exceeds cap + margin
_SIM_THRESHOLD = 0.88      # store-search score at/above which two topics are near-duplicate
_RECENCY_HALF_LIFE_DAYS = 30.0
_W_RECENCY = 1.0
_W_IMPORTANCE = 2.0        # importance outweighs recency, so valuable facts survive age
_LOAD_LIMIT = 1000         # ceiling on items pulled for one pass


def _enabled() -> bool:
    return os.getenv("SEMANTIC_MEMORY_PRUNE", "").strip().lower() == "on"


def _kind(item: SearchItem) -> str:
    """Best-effort kind, tolerant of items written without an explicit tag."""
    value = item.value or {}
    kind = value.get("kind")
    if kind:
        return kind
    content = value.get("content")
    if isinstance(content, dict) and "topic" in content:
        return _TOPIC
    return _PROFILE if isinstance(content, dict) else ""


def _topic_text(item: SearchItem) -> str:
    content = (item.value or {}).get("content") or {}
    return (content.get("topic") or "").strip() if isinstance(content, dict) else ""


def _recall_count(meta: dict[str, dict], key: str) -> int:
    return (meta.get(key) or {}).get("recall_count", 0)


def _recency(updated_at: datetime | None, now: datetime) -> float:
    """1.0 for a fresh item, decaying by half every _RECENCY_HALF_LIFE_DAYS. A gentle
    decay so age nudges the score without being able to dominate importance."""
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)


def _score(item: SearchItem, meta: dict[str, dict], now: datetime) -> float:
    return _W_RECENCY * _recency(item.updated_at, now) + _W_IMPORTANCE * _recall_count(meta, item.key)


def _best(cluster: list[SearchItem], meta: dict[str, dict]) -> SearchItem:
    """Representative of a near-duplicate cluster: most-recalled, tie-break most-recent."""
    return max(
        cluster,
        key=lambda it: (_recall_count(meta, it.key), it.updated_at or datetime.min.replace(tzinfo=timezone.utc)),
    )


def _needs_pass(items: list[SearchItem], profiles: list[SearchItem]) -> bool:
    """Size-debounce: a full pass is worth it only when the namespace is over its
    ceiling or has duplicate profiles (a correctness issue we always fix)."""
    return len(items) > _TOPIC_CAP + _TRIGGER_MARGIN or len(profiles) > 1


def _merge_profiles(profiles: list[SearchItem]) -> dict:
    """One profile from many: most-recent non-null scalar wins; list fields union."""
    ordered = sorted(
        profiles,
        key=lambda p: p.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    merged: dict = {"response_language": None, "citation_style": None,
                    "practice_areas": [], "frequent_acts": []}
    seen = {"practice_areas": set(), "frequent_acts": set()}
    for p in ordered:
        content = (p.value or {}).get("content") or {}
        for scalar in ("response_language", "citation_style"):
            if merged[scalar] is None and content.get(scalar):
                merged[scalar] = content[scalar]
        for field in ("practice_areas", "frequent_acts"):
            for val in content.get(field) or []:
                if val not in seen[field]:
                    seen[field].add(val)
                    merged[field].append(val)
    return merged


async def _dedupe_profiles(store: BaseStore, ns: tuple[str, str], profiles: list[SearchItem]) -> None:
    if len(profiles) <= 1:
        return
    canonical = max(
        profiles,
        key=lambda p: p.updated_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    await store.aput(ns, canonical.key, {"kind": _PROFILE, "content": _merge_profiles(profiles)})
    for p in profiles:
        if p.key != canonical.key:
            await store.adelete(ns, p.key)


async def _consolidate_topics(
    store: BaseStore, ns: tuple[str, str], topics: list[SearchItem], meta: dict[str, dict]
) -> tuple[list[SearchItem], list[str]]:
    """Cluster near-duplicate topics via the store's own vector search and keep one
    representative per cluster. Returns (survivors, dropped_keys)."""
    handled: set[str] = set()
    survivors: list[SearchItem] = []
    dropped: list[str] = []
    for item in topics:
        if item.key in handled:
            continue
        text = _topic_text(item)
        if not text:
            handled.add(item.key)
            survivors.append(item)
            continue
        peers = await store.asearch(ns, query=text, limit=len(topics))
        cluster = [item]
        for p in peers:
            if p.key == item.key or p.key in handled or _kind(p) != _TOPIC:
                continue
            if (p.score or 0.0) >= _SIM_THRESHOLD:
                cluster.append(p)
        rep = _best(cluster, meta)
        for c in cluster:
            handled.add(c.key)
            if c.key != rep.key:
                dropped.append(c.key)
        survivors.append(rep)
    for key in dropped:
        await store.adelete(ns, key)
    return survivors, dropped


async def prune_memory(store: BaseStore | None, user_id: str | None) -> None:
    """Consolidate + cap a practitioner's Semantic Memory. Fail-open; no-op when the
    namespace is small or the flag is off."""
    if not _enabled():
        return
    if store is None or not user_id or user_id == _ANONYMOUS:
        return
    ns = (user_id, "semantic")
    try:
        items = await store.asearch(ns, limit=_LOAD_LIMIT)
        profiles = [i for i in items if _kind(i) == _PROFILE]
        topics = [i for i in items if _kind(i) == _TOPIC]
        if not _needs_pass(items, profiles):
            return

        meta = await stats.aload_hits(store, user_id)
        await _dedupe_profiles(store, ns, profiles)
        survivors, dropped = await _consolidate_topics(store, ns, topics, meta)

        now = datetime.now(timezone.utc)
        survivors.sort(key=lambda it: _score(it, meta, now), reverse=True)
        evicted = [it.key for it in survivors[_TOPIC_CAP:]]
        # Never empty the namespace: keep at least the capped topics + any profile.
        for key in evicted:
            await store.adelete(ns, key)

        await stats.adelete_hits(store, user_id, dropped + evicted)
    except Exception:
        logger.warning("semantic memory pruning failed; store unchanged for this pass", exc_info=True)


# Keep in-flight pruning tasks referenced so the loop can't GC them once the request returns.
_pending: set[asyncio.Task] = set()


def schedule_pruning(store: BaseStore | None, user_id: str | None) -> None:
    """Fire-and-forget a pruning pass after the response is delivered; all gating,
    debouncing, and error handling live in prune_memory."""
    try:
        task = asyncio.create_task(prune_memory(store, user_id))
    except RuntimeError:  # no running loop
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)
