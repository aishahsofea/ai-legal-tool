# Agent Hardening Backlog

Future implementation items captured from the agent-graph review so they are not lost.

## Immediate hardening candidates

These are likely needed before a paid or lawyer-facing pilot.

- Add a grounding-check node between `synthesiser` and `supervisor` to verify that each legal claim in the answer is supported by the cited retrieved section text.
- Add deterministic citation validation against retrieved chunks and Act metadata instead of relying on prose regex alone.
- Add exact statute lookup retrieval for queries that mention a specific Act/section, bypassing embeddings when possible.
- Fail closed when supervisor violations remain after retries; do not return a known non-compliant draft as the final answer.
- Move retry control flow from `query_lifecycle.py` into the LangGraph graph via conditional edges so graph traces match actual execution.
- Use query-type-specific retrieval strategies: exact lookup for `statute_lookup`, hybrid search for `topical`, metadata/SQL retrieval for `provision_extraction`.

## Retrieval improvements

- Add BM25 / Postgres full-text search alongside pgvector semantic search for topical queries.
- Combine dense and lexical rankings with Reciprocal Rank Fusion.
- Add retrieval relevance grading before synthesis.
- Add bounded query rewriting on retrieval miss or low relevance, with at most one rewrite round.
- Add optional reranking for topical queries once evals are large enough to justify the latency.
- Extract Act aliases and acronyms such as `PDPA`, `CPC`, `Evidence Act`, and `Federal Constitution` into a lookup table.
- Add section-number and Act-title extraction helpers for exact lookup queries.
- Add retrieval depth per query type instead of fixed top-8 for all queries.

## Legal-source currency and metadata

- Add chunk-level `status` metadata such as `in_force`, `repealed`, `amended`, or `unknown`.
- Add `as_at_date`, `source_pdf_url`, `source_pdf_type`, and `last_amended_date` fields to chunks or source metadata.
- Hard-filter production retrieval to in-force legislation unless the user explicitly asks for historical/repealed law.
- Surface amendment/status metadata in citations when available.
- Build a migration/backfill path from existing `data/acts_metadata/*.json` into the database.
- Record which PDF version each chunk was extracted from.

## Graph architecture and observability

- Add LangGraph checkpointer support, likely PostgresSaver, before human-in-the-loop or persisted multi-turn workflows.
- Require and propagate `thread_id` for durable graph runs.
- Use `graph.invoke` and `graph.astream` as the single lifecycle path instead of duplicating node calls in streaming and non-streaming code.
- Add node-level tracing tags: `query_type`, retrieval strategy, model, retry count, citation count, violation count.
- Add LangSmith dataset/eval integration beyond local JSON evals.
- Persist audit logs for final answers, citations, violations, and retrieved source IDs.

## Safety and policy improvements

- Add router confidence to structured output.
- Add clarification interrupts for low-confidence routing or ambiguous jurisdiction.
- Add jurisdiction detection, especially civil vs Syariah/state-law ambiguity.
- Expand escalation detection beyond keyword matching using a small classifier or structured LLM route.
- Add safe fallback responses for failed synthesis, failed grounding, or repeated policy violations.
- Consider a bounded Reflexion/critic node after groundedness evals exist.

## Bilingual support

- Build a BM-heavy eval set before claiming strong bilingual support.
- Ingest official BM PDFs where available and link BM chunks to English chunks by `act_number + section_number`.
- Compare `text-embedding-3-small`, `text-embedding-3-large`, and multilingual models such as `bge-m3` on BM/code-switched retrieval.
- Consider query translation as a retrieval pre-processing fallback for BM queries.
- Decide how to cite authoritative English text while answering in BM.

## Eval expansion

- Expand the golden set from the current small dataset to roughly 200 manually verified cases.
- Add retrieval-specific metrics: expected section retrieved in top-1/top-3/top-8.
- Add groundedness metrics: claims supported, partially supported, unsupported.
- Add exact-citation stress cases such as Section 114A vs 144.
- Add acronym cases: PDPA, CPC, MACC Act, Federal Constitution.
- Add BM and code-switched cases.
- Add negative cases where the correct answer is “retrieved sections do not contain enough information.”
- Add regression cases for supervisor final-failure behavior.

## Infrastructure and operational polish

- Replace per-query psycopg2 connections with a connection pool.
- Add PDF metadata cache refresh or TTL for `_pdf_url_map()`.
- Remove unused imports and tighten type annotations.
- Change `AgentState.query_type` from `str` to a `Literal` union.
- Add database indexes for direct lookup: `(act_number, section_number)`, normalized `act_title`, and possibly full-text `tsvector`.
- Add migrations rather than documenting schema only in README.

## Deferred product features

- Human review queue for escalated or low-confidence answers.
- Persistent user/session history.
- Source-version audit view for lawyers.
- Case-law corpus once a reliable source is available.
- Subsidiary legislation ingestion.
- Historical-law mode for repealed/amended legislation.
