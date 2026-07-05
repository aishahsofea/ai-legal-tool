"""Manual eval for Semantic Memory recall + pruning (ADR 0010, Phase 4).

NOT a unit test — it's an instrument for *tuning* recall and the pruner's cap /
similarity threshold / score weights. The deterministic sweep is free; the live
check makes one real `gpt-4.1-mini` synthesis call (~$0.0005) and needs an OpenAI key.

It proves the two properties the feature rests on:
  1. Recall HELPS  — a genuinely valuable, recurring fact surfaces in the top
     `_RECALL_LIMIT` and reaches the synthesiser as framing.
  2. Recall doesn't POLLUTE — stale / low-value / near-duplicate noise does not
     crowd the valuable fact out of the top slots.
And a pruner sweep: after a pass, duplicate profiles collapse to one, near-duplicate
topics consolidate, and low-value topics beyond the cap are evicted while
high-value+recent survive.

Usage:
    python -m evals.semantic_memory              # deterministic sweep + live synthesis
    python -m evals.semantic_memory --dry        # deterministic sweep only (no API call)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import os

from dotenv import load_dotenv

load_dotenv()

from langgraph.store.memory import InMemoryStore

from agent.memory import pruner, stats
from agent.nodes.recall import _RECALL_LIMIT, recall_node

SEP = "-" * 68
USER = "user-eval"
NS = (USER, "semantic")

# The valuable, recurring fact the practitioner keeps returning to. It must survive
# pruning and surface in recall above the noise.
VALUABLE_TOPIC = "unfair dismissal remedies"
# A near-duplicate phrasing of the valuable topic — the over-update the extractor
# produces and the pruner is meant to consolidate away.
DUP_TOPIC = "remedies unfair dismissal"
# One-off / low-value noise topics that should never crowd out the valuable one.
NOISE_TOPICS = [
    "company incorporation steps",
    "stamp duty exemption thresholds",
    "trademark opposition deadlines",
    "winding up petition grounds",
]
QUERY = "What remedies are available for an unfair dismissal claim?"


# --- Deterministic stub embedding (shared with tests/test_pruner.py) ----------------
# Indexing only content.topic keeps topic vectors clean of structural tokens, so a
# reordered duplicate scores 1.0 and an unrelated topic scores 0.0 — reproducible
# clustering without an API call. Real embeddings are used on the live path.
def _stub_embed(texts: list[str]) -> list[list[float]]:
    dims = 64
    out = []
    for text in texts:
        vec = [0.0] * dims
        for word in text.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


STUB_INDEX = {"dims": 64, "embed": _stub_embed, "fields": ["content.topic"]}


def _topic(store: InMemoryStore, key: str, topic: str) -> None:
    store.put(NS, key, {"kind": "RecurringTopic", "content": {"topic": topic}})


def _profile(store: InMemoryStore, key: str, content: dict) -> None:
    store.put(NS, key, {"kind": "PractitionerProfile", "content": content})


def _seed(store: InMemoryStore) -> None:
    # Two profiles to collapse into one (over-insert the extractor can produce).
    _profile(store, "profile-a", {"response_language": "bm", "practice_areas": ["employment"]})
    _profile(store, "profile-b", {"citation_style": "prefers brief answers", "practice_areas": ["employment", "labour"]})
    # The valuable topic + its near-duplicate, plus noise.
    _topic(store, "valuable", VALUABLE_TOPIC)
    _topic(store, "dup", DUP_TOPIC)
    for i, topic in enumerate(NOISE_TOPICS):
        _topic(store, f"noise-{i}", topic)
    # Make the valuable topic genuinely high-value: several recorded recalls.
    store.put(stats.meta_namespace(USER), "valuable",
              {"recall_count": 6, "last_recalled": "2026-07-01T00:00:00+00:00"}, index=False)


def _all_topics(store: InMemoryStore) -> list[str]:
    items = store.search(NS, limit=100)
    return sorted(_t for item in items
                  if (_t := (item.value or {}).get("content", {}).get("topic")))


def _profile_keys(store: InMemoryStore) -> list[str]:
    return sorted(item.key for item in store.search(NS, limit=100)
                  if (item.value or {}).get("kind") == "PractitionerProfile")


def run_sweep() -> None:
    store = InMemoryStore(index=STUB_INDEX)
    _seed(store)

    print(SEP)
    print("SEED")
    print(f"  profiles: {_profile_keys(store)}")
    print(f"  topics  : {_all_topics(store)}")
    print(SEP)

    # 1 + 2: recall over the seeded store.
    os.environ["SEMANTIC_MEMORY_RECALL"] = "on"
    recalled = recall_node({"query": QUERY}, {"configurable": {"user_id": USER}}, store=store).get("recalled_memory", "")
    surfaced = [line[2:] for line in recalled.splitlines()]
    helps = any(VALUABLE_TOPIC in line for line in surfaced)
    print(f"RECALL  (query={QUERY!r}, top-{_RECALL_LIMIT})")
    for line in surfaced:
        print(f"    {line}")
    print(f"  HELPS?          : {'YES — valuable topic surfaced' if helps else 'NO'}")
    print(f"  crowded out?    : {'no — within top slots' if len(surfaced) <= _RECALL_LIMIT else 'YES'}")
    print(SEP)

    # 3: pruner sweep. Shrink the cap so the seeded noise exercises eviction in a
    # small fixture (production keeps the generous default).
    os.environ["SEMANTIC_MEMORY_PRUNE"] = "on"
    effective_cap = 3
    original_cap, original_margin = pruner._TOPIC_CAP, pruner._TRIGGER_MARGIN
    pruner._TOPIC_CAP, pruner._TRIGGER_MARGIN = effective_cap, 0
    try:
        asyncio.run(pruner.prune_memory(store, USER))
    finally:
        pruner._TOPIC_CAP, pruner._TRIGGER_MARGIN = original_cap, original_margin

    topics_after = _all_topics(store)
    profiles_after = _profile_keys(store)
    print("AFTER PRUNE")
    print(f"  profiles: {profiles_after}  ({'collapsed to one' if len(profiles_after) == 1 else 'UNEXPECTED'})")
    print(f"  topics  : {topics_after}")
    print(f"  valuable survived? : {'YES' if VALUABLE_TOPIC in topics_after else 'NO'}")
    print(f"  duplicate gone?    : {'YES' if DUP_TOPIC not in topics_after else 'no'}")
    print(f"  capped to {effective_cap}? : {'YES' if len(topics_after) <= effective_cap else 'no'}")
    print(SEP)


def run_live() -> None:
    from agent.graph import _STORE_INDEX
    from agent.nodes.synthesiser import synthesiser_node

    store = InMemoryStore(index=_STORE_INDEX)
    _seed(store)

    os.environ["SEMANTIC_MEMORY_RECALL"] = "on"
    recalled = recall_node({"query": QUERY}, {"configurable": {"user_id": USER}}, store=store).get("recalled_memory", "")

    print("LIVE SYNTHESIS  (real embeddings + one gpt-4.1-mini call)")
    print(f"  recalled memory the synthesiser sees:\n    " + recalled.replace("\n", "\n    "))
    state = {
        "query": QUERY,
        "retrieved_chunks": [{
            "act": "Industrial Relations Act 1967", "section": "20",
            "text": "A workman may make representations to be reinstated where he considers his dismissal without just cause or excuse.",
        }],
        "history": [],
        "recalled_memory": recalled,
    }
    draft = synthesiser_node(state).get("draft_response", "")
    print(f"  draft answer:\n    " + draft.replace("\n", "\n    "))
    print(SEP)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune Semantic Memory recall + pruning.")
    parser.add_argument("--dry", action="store_true", help="deterministic sweep only, no API call")
    args = parser.parse_args()

    run_sweep()
    if not args.dry:
        run_live()


if __name__ == "__main__":
    main()
