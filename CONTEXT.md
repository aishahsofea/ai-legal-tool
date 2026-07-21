# Malaysian Legal Research Assistant

An AI agent that helps Malaysian law practitioners research legislation and case law. The system retrieves and cites authoritative legal sources; it does not give legal advice and escalates to a human lawyer when needed.

## Language

**Act**:
A federal statute published in the Laws of Malaysia (LOM) portal at lom.agc.gov.my.
_Avoid_: law, bill, legislation (too broad), statute

**Updated Act**:
An Act that has been amended and the latest version is maintained on the LOM portal. Identified by a numeric Act number.
_Avoid_: current Act, live Act

**Revised Act**:
An Act revised under the Revision of Laws Act 1968. Has a numeric Act number; treated identically to Updated Acts in the pipeline.

**Repealed Act**:
An Act no longer in force. Retained in the index for historical research but excluded from the main knowledge base by default.

**Subsidiary Legislation**:
Regulations, rules, or orders made under an Act. Referenced by P.U. number (e.g. P.U. (A) 49/2014). Governed by the parent Act.
_Avoid_: sub-act, regulations (alone)

**Reprint**:
A consolidated version of an Act that incorporates amendments up to a given date. The `latest_reprint_pdf` field is the canonical source selected by the scraper and may be English or BM; its registered language is derived from AGC metadata/URL markers, never from a legacy local directory name.
_Avoid_: latest version, current version

**Citation Receipt**:
The in-app verification experience opened from a provenance-backed citation. It keeps the delivered claim and its source visible together, renders one physical PDF page at a time, and draws a highlight only for a uniquely matched **Evidence Span**. On desktop it is a right-hand drawer; on narrower screens it is a full-screen sheet.
_Avoid_: PDF link, source popup

**Receipt Document**:
An immutable, manifest-identified PDF snapshot whose bytes are exactly those used by one **Extraction Run**. Its content-derived identity includes Act, source language, and full SHA-256; byte size and page count are also checked before enrichment, location, or delivery. Multiple languages and historical versions may exist for one Act.
_Avoid_: latest PDF, remote PDF, Official Source Link

**Extraction Run**:
A deterministic extraction of one **Receipt Document**, identified by document identity, extractor/version, and configuration hash. It owns a chunk-set hash and a hash-verified word-coordinate sidecar. Retrieval chunks carry its `document_id`, `extraction_id`, content hash, and page bounds.

**Active Corpus Mapping**:
The reversible pointer from one `(Act, language)` pair to a ready **Receipt Document** and **Extraction Run**. New bytes are registered and shadow-ingested before this pointer moves; the prior mapping remains in activation history for rollback.

**Corpus Rollout**:
The idempotent operator workflow that prepares missing immutable assets, applies the provenance migration, registers identities, ingests only absent **Extraction Runs**, and advances **Active Corpus Mappings** only for verified successes. It is normally run as one resumable command; the individual lifecycle commands are recovery controls, not required setup steps.

**Evidence Span**:
A legal claim from the delivered draft plus one short, contiguous supporting quote. It exists only after application code independently confirms the supported label, cited Act/section, claim occurrence in the draft, and quote occurrence in the retrieved chunk. Partial, unsupported, hallucinated, overlong, and duplicate spans are excluded.
_Avoid_: model highlight, source chunk

**Locator Result**:
The outcome of strict matching for an **Evidence Span** against the exact **Extraction Run** coordinate sidecar: `matched`, `not_found`, or `ambiguous`. Only a unique contiguous normalized-token match produces page-grouped rectangles. The citation `page_number` is merely the fallback section-start page, not proof that evidence occurs there.

**Official Source Link**:
The citation's remote AGC `pdf_url`, offered separately as “Check latest on AGC”. It lets a practitioner inspect the government portal's current remote source, but it is not the **Receipt Document** and its bytes are never used to assert an exact highlight.

**Timeline Entry**:
A dated version event for an Act: ORIGINAL, REPRINT, REPRINT ONLINE, or AMENDMENTS. Stored in the `timeline` array of each act metadata file.

**Case Law**:
Court judgments (decisions). Not in scope for v1. Planned for v2 via CommonLII (commonlii.org/my/).
_Avoid_: cases, judgments (until v2 is scoped)

**Legal Research Query**:
A practitioner's question directed at the agent with legal-research substance. May be statute lookup ("what does Section X of Act Y say?"), topical ("which Acts govern data privacy in Malaysia?"), or comparative. Does NOT include requests for legal advice about a specific situation. Not every input is a **Legal Research Query** — a **Conversational Turn** carries no legal substance and is handled separately.

**Conversational Turn**:
A message with no legal-research substance — a greeting, self-introduction or name, thanks, small talk, or a meta question about the assistant ("what can you do?", "how does this work?"). The router classifies these as `conversational` only when they are *unambiguously* social or meta; anything with legal substance stays on the legal path. A **Conversational Turn** is answered directly with a short, warm reply that bypasses retrieval and the **Supervisor Rules** — it carries no citations and no disclaimer. It still mirrors the query language and reads **Conversation History** (so the agent can recall a name given earlier), and it also reads recalled **Semantic Memory** — the same `recall` step that precedes the synthesiser runs before it too, so saved preferences can personalise the reply. A **Conversational Turn** also *writes* to Semantic Memory: a self-introduction ("I'm a software engineer exploring legal tech") is where a practitioner's own background surfaces, and that background is a durable fact worth remembering (ADR 0012). Only the practitioner's *own* professional identity is stored this way — confidential client/matter facts and sensitive personal life are excluded by construction.

**Conversation History**:
The prior turns in the same thread, passed as a list of user/assistant messages. Used to interpret follow-up questions like "what about criminal cases?". For v1, the most recent turns are kept within a token budget (trimmed in whole user+assistant turns, never split mid-turn; the most recent turn is always kept). The stored assistant turn is the *delivered* response — including the safe fallback when a turn is fail-closed — so history always mirrors what the practitioner actually received, never a rejected draft.

**Standalone Query**:
The history-resolved, self-contained version of a follow-up **Legal Research Query**. A short or elliptical follow-up ("what about criminal cases?", "and in Bahasa?") is rewritten into a query that carries forward the act, topic, or section from **Conversation History** so it can be retrieved on its own. Used only for retrieval; it is never shown to the practitioner and never recorded in **Conversation History** (which always stores what the practitioner actually typed).
_Avoid_: expanded query, resolved query

**Retrieval Agent**:
The tool-calling form of the retrieval step (flag `AGENTIC_RETRIEVAL`, ADR 0013). Rather than a fixed "exact-lookup-else-vector-search" dispatch, an LLM binds two **Retrieval Tools** — `search_statutes` (semantic search) and `lookup_section` (exact section lookup) — and decides which to call, with what arguments, and whether to search again when results look weak. It gathers sources only; it never drafts the answer. It **fails open** to the deterministic retriever, so it can never return less than the proven path.
_Avoid_: calling it "the retriever" without qualification (that name is the deterministic node); "search agent"

**Re-retrieval**:
The retry behaviour where an **Evidence Violation** (a citation absent from the retrieved sources, or a grounding check flagging an unsupported claim) sends the turn back to the **Retrieval Agent** with feedback about the gap, instead of re-drafting against the same sources. A policy/phrasing violation still re-drafts. Bounded by the same single-retry budget — one *smarter* retry, not more loops. Only engages when `AGENTIC_RETRIEVAL` is on.
_Avoid_: "retry" unqualified (there are two kinds — re-draft vs re-retrieve)

**Practitioner**:
The human using the assistant across research threads. Identified by a **User Id** — a UUID generated and persisted in the practitioner's browser and sent with every query. This is weak, per-browser identity (there is no authentication in v1); it is the scope key that lets **Semantic Memory** outlive a single thread.
_Avoid_: account, session (a session is one thread; a **Practitioner** spans many)

**Semantic Memory**:
Durable facts about a **Practitioner** that persist across research threads — their own professional background, response-language preference, citation/format style, practice-area focus, frequently-referenced **Acts**, and recurring research topics. Stored in a cross-thread store namespaced by **User Id**, extracted in the background after a turn (legal or conversational), and read back to personalise later turns. Distinct from **Conversation History**, which is one thread's transcript. Confidential client or matter facts are **never** stored here.
_Avoid_: long-term memory (ambiguous — name the tier), profile (that is one part of it)

**Recurring Topic**:
A research subject a **Practitioner** returns to across threads (e.g. "data-breach penalties", "unfair dismissal"). Held as a growing collection in **Semantic Memory** and used to bias retrieval. Contrast a one-off **Legal Research Query**, which is not on its own a **Recurring Topic**.

**Working Memory**:
The slice of context actually placed in a prompt for the current turn — the token-budget-trimmed **Conversation History** plus any recalled **Semantic Memory** facts. Derived at read time, never stored.
_Avoid_: context window (that is the model limit, not this projection)

**Legal Advice** _(out of scope)_:
A recommendation about what a specific person should do in a specific legal situation. The agent must never produce this; it hands off to a human lawyer instead.

## Relationships

- An **Act** has one or more **Timeline Entries**
- An **Act** may have multiple immutable **Receipt Documents** across languages and historical versions
- An **Active Corpus Mapping** selects one ready **Extraction Run** per Act/language without deleting history
- A provenance-backed citation may carry zero or more validated **Evidence Spans** and opens one shared **Citation Receipt**
- A **Locator Result** maps one selected **Evidence Span** to physical rectangles in the **Receipt Document**; uncertainty maps to no rectangles
- The **Official Source Link** remains separate from the **Receipt Document** because remote bytes and pagination can change
- An **Act** may have zero or more **Subsidiary Legislation** items
- The most recent **Reprint** Timeline Entry is the canonical text used for ingestion
- A **Legal Research Query** is answered using **Acts** (v1) and eventually **Case Law** (v2)
- A **Practitioner** owns one or more research threads, each with its own **Conversation History**
- A **Practitioner** has one **Semantic Memory** (scoped by **User Id**) spanning all their threads
- **Semantic Memory** holds zero or more **Recurring Topics**
- **Working Memory** for a turn is built from that turn's **Conversation History** plus recalled **Semantic Memory**

## Example dialogue

> **Practitioner:** "What are the penalties under the Personal Data Protection Act?"
> **Agent:** Retrieves the relevant sections from the PDPA Reprint, cites the section numbers, and summarises — but does not advise whether a specific data breach constitutes a violation.

## Supervisor Rules

These constraints apply to **legal-answer turns** only — a **Conversational Turn** bypasses retrieval and the supervisor entirely. The agent enforces them on every legal response before output:

1. **No advice on specific facts** — response must not contain "you should", "you must", "in your case", "I recommend"
2. **Citation required** — a legal answer must cite at least one authoritative source ("Section X of Act Y"). This is an answer-level presence check. Whether each individual legal claim is actually *supported* by its cited section is a separate grounding concern, not part of this deterministic rule.
3. **Hedging required** — response must include a disclaimer that it is not a substitute for professional legal advice
4. **Escalation trigger** — if the query contains "my client", "I have been charged", "am I liable", route to human hand-off before retrieval starts

## Query Language Behaviour

Malaysian law practitioners code-switch heavily — mixing BM and English in a single query ("tolong check Section 14 Evidence Act"). The system may retrieve English and BM chunks together. A citation and quotation retain the registered source language; BM-only Acts 144, 152, 194, 220, 228, and 230 must never be relabeled as English. Response prose mirrors the dominant language of the query.

## Interruption: two distinct mechanisms

A turn can stop mid-flight for two unrelated reasons, and the system keeps them separate:

- **Clarification** is *graph-initiated*. When a **Legal Research Query** is un-actionable as written — most often a section number with no Act named — the router routes to the `clarify` node, which calls LangGraph's `interrupt()`. The turn suspends on its checkpoint, an `interrupt` SSE event carries the question to the practitioner, and the graph resumes only on `POST /resume { thread_id, value }`. The answer is **merged** with the original query into one self-contained query (so retrieval sees the full intent, not the bare answer) and re-classified; a turn asks at most one clarifying question. See ADR 0015.
- **Barge-in** is *user-initiated* cancellation — the practitioner presses Stop/Esc (`POST /cancel`, or a new prompt on the same thread). It aborts the in-flight run; nothing is written. See ADR 0014.

Both rely on the same `thread_id` checkpoint continuation, but one *pauses for input* while the other *aborts the run* — they never share a code path. A **Conversational Turn** and an **escalate** hand-off are separate short-circuits again: neither pauses nor cancels, they just skip the pipeline.

## Observability

When `LANGSMITH_TRACING` is on, every turn is traced to LangSmith. Beyond the free
node-level trace, the query lifecycle (`agent/query_lifecycle.py`) labels each run —
`run_name=legal_query`, a `source` (`api` vs `eval`), active feature flags, and
`user_id`/`thread_id` metadata — and posts the turn's quality outcome as run
**feedback** (`agent/observability.py`): `passed`, violation/citation counts,
`retry_count`, `fallback_delivered`, `escalated`, and categorical `query_type`.
These are the same signals the **Supervisor Rules** and evidence checks compute, so
groundedness and pass-rate become chartable over time. Feedback is fail-open and off
the hot path — it never changes or delays a **Legal Research Query** response.

Receipt delivery separately emits structured availability, integrity, delivery, and locator-outcome events. The browser reports only allowlisted render/request failure metadata; claims, quotes, and source URLs are never included.

## Evaluation dashboard

An **Eval Run** is a single, explicitly selected slice of the hand-validated eval dataset. It is
not prompt-version history. The developer dashboard separates two views:

- **Coverage** is static metadata derived from `evals/dataset.json`: case counts, smoke coverage,
  policy balance, scenarios, and advisory gap flags. It remains available without a database.
- **Effectiveness** is the result of a live **Eval Run**: deterministic L1 assertions followed by
  the LLM judge only when L1 passes, with pass rates grouped by scenario for that run.

Live runs execute one at a time in an isolated subprocess against `EVALS_DATABASE_URL`, never the
application's `DATABASE_URL`. The API checks that every citation-applicable Act/section pair exists
in the dedicated eval corpus before starting, streams each completed case as JSONL-backed SSE, and
terminates the subprocess on explicit cancellation or browser disconnect. `CHECKPOINTER=memory` is
forced because every eval case is a fresh single-turn thread; the eval database therefore stores
only curated `chunks`.

The API surface is `GET /evals/coverage`, `POST /evals/run`, `POST /evals/cancel`, and
`GET /evals/results`. The standalone Next.js `/evals` route is exposed only when
`NEXT_PUBLIC_EVALS=1` at build time.

## Flagged ambiguities

- "legislation" was used loosely to mean both Acts and Subsidiary Legislation — resolved: use **Act** for statutes and **Subsidiary Legislation** for P.U. instruments.
- "case" was used to mean both court judgments and use-cases — resolved: **Case Law** for court judgments only.
