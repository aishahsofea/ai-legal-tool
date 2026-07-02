# Agent memory lifecycle: episodic / semantic / working

Date: 2026-07-02

Agent memory is split into **three tiers with three independent lifecycles**, rather than treated as one "conversation memory" backed by the checkpoint. Conflating them was the root of the design gap: the LangGraph checkpoint is *episodic* persistence only, and stretching it (or the history token budget) to cover cross-session knowledge would have scaled cost and latency faster than context quality.

| Tier | What it is | Backing store | Scope key | Lifecycle |
| --- | --- | --- | --- | --- |
| **Episodic** | The verbatim transcript of one research thread — an audit artifact. | LangGraph checkpoint (`PostgresSaver`) | `thread_id` | Append-only, immutable. Never summarised destructively (see ADR 0008). |
| **Working** | The slice of history + recalled facts actually placed in a prompt for the current turn. | Derived at read time, not stored. | `thread_id` | Rebuilt every turn: token-budget trim (ADR 0008) + recalled semantic facts. |
| **Semantic** | Durable facts about a **practitioner**: preferences and recurring research topics. | LangGraph `BaseStore` (Postgres + pgvector) | `user_id` | Extracted in the background, merged/deduped, pruned by importance+recency. |
| **Procedural** | Learned behaviour / prompt rules. | — | — | Out of scope for v1. The Supervisor Rules are hand-authored, not learned. |

## Decisions

- **Semantic memory attaches to a `user_id`, not a `thread_id`.** Episodic memory is correctly thread-scoped; semantic memory is worthless thread-scoped because its whole point is surviving across threads. The scope key is a **client-persisted `user_id`** (a UUID generated and stored in the browser, sent alongside `thread_id` on every `/query`). This is deliberately *weak* identity — per-browser, not authenticated — chosen because the app has no auth and building it is a separate, larger piece of work. Real accounts are the eventual upgrade path; the memory namespace `(user_id, "semantic")` does not change when identity gets stronger.
- **We remember preferences + recurring topics, not client/matter facts.** The extraction schema captures: response language, citation/format style, practice-area focus, frequently-referenced **Acts**, and recurring research topics. Confidential client or matter facts mentioned in chat are **excluded by construction** — pulling them into a durable store would create retention and privilege obligations a pilot is not equipped to honour.
- **Extraction runs in the background, off the hot path.** The turn's response never waits on memory extraction. The hot path only *reads* recalled facts; writing (extract → merge → upsert) happens after the turn is delivered.
- **LangMem is the extract/merge/persist layer.** It provides a background memory manager over a `BaseStore` and uses Trustcall underneath for schema-driven, dedup-aware upserts. Chosen over calling Trustcall directly (less glue) and over a hand-rolled extractor (less to maintain, and the collection/merge semantics are the hard part we do not want to reinvent).
- **Collection strategy, over-update accepted.** Recurring topics are a growing collection, not a single overwritten profile. The known trade-off is a tendency to over-update / accrete near-duplicates; acceptable at pilot size and the reason pruning (below) is designed now even though it ships later.
- **Pruning is importance + recency, not TTL alone.** TTL reclaims storage but does not improve retrieval quality — it can evict a stale-but-valuable fact while keeping recent chatter. The eviction policy combines recency with importance / retrieval-frequency (or an offline evaluator), so valuable memories survive and low-value ones decay. Deferred in implementation, fixed in direction.
- **Compression stays retrieve-then-trim, summarise only under pressure.** Consistent with ADR 0008: the first lever is retrieving only task-relevant facts and trimming by token budget. A summary buffer is added only when a *reproduced* eval shows a generous budget still dropping a needed referent — not because a conversation "feels long."

## Considered options

- **Scope: keep everything on `thread_id`.** Rejected. Simplest, but produces no cross-session memory at all — it is episodic memory wearing a semantic label.
- **Scope: real authentication now.** Deferred. The correct long-term identity, but a large separate workstream that would block all memory work behind an auth build. The namespace is designed so this is a later swap, not a migration.
- **Scope: per-matter.** Deferred. Fits legal workflows well and is a likely v2 refinement, but there is no matter model or UI today.
- **Content: full durable extraction incl. matter facts.** Rejected for v1 on privacy grounds (see decision above).
- **Library: Trustcall directly / hand-rolled.** Rejected/deferred. Both viable; LangMem wraps the parts (background manager + store binding) we would otherwise hand-write.
- **Hot-path memory tools.** Rejected as the default. Adds latency to every turn; background extraction gets the same durable facts without taxing the response path.

## Consequences

- **API contract changes.** `/query` now accepts `user_id` alongside `thread_id`. The frontend generates and persists it. Documented in `README.md` / `CONTRIBUTING.md`.
- **New store.** A `BaseStore` (Postgres + pgvector) is created alongside the checkpointer, namespaced by `(user_id, "semantic")`, with embeddings via the existing `text-embedding-3-small` model used for statutes.
- **New dependency + config.** `langmem` is added; a flag gates recall/extraction so the memory path can be turned off without code changes.
- **New failure surface, fail-open.** Recall and extraction must never break a turn: on any memory error the agent behaves exactly as it does today (no recalled facts, no extraction), mirroring the fail-open contract of `contextualize`.
- **Pruning is a known debt.** Nothing is deleted at pilot size; the importance+recency policy is specified here so it is a scheduled build, not a rediscovered problem.

## Related

- ADR 0008 — token-budget history trimming (the *working*-memory read projection this builds on).
- ADR 0007 — history-aware retrieval escalation boundary (raw query is never overwritten; recall must respect the same boundary).
