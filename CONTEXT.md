# Malaysian Legal Research Assistant

An AI agent that helps Malaysian law practitioners research legislation and case law. The system retrieves and cites authoritative legal sources; it does not give legal advice and escalates to a human lawyer when needed.

## Language

**Act**:
A federal statute published in the Laws of Malaysia (LOM) portal at lom.agc.gov.my.
_Avoid_: law, bill, legislation (too broad), statute

**Updated Act**:
An Act that has been amended, with the latest version maintained on the LOM portal. Has a numeric Act number.
_Avoid_: current Act, live Act

**Revised Act**:
An Act revised under the Revision of Laws Act 1968. Has a numeric Act number; treated identically to Updated Acts in the pipeline.

**Repealed Act**:
An Act no longer in force. Kept in the index for historical research, excluded from the main knowledge base by default.

**Subsidiary Legislation**:
Regulations, rules, or orders made under an Act. Referenced by P.U. number (e.g. P.U. (A) 49/2014). Governed by the parent Act.
_Avoid_: sub-act, regulations (alone)

**Reprint**:
A consolidated version of an Act, incorporating amendments up to a given date. `latest_reprint_pdf` is the canonical source the scraper selects — may be English or BM. Its registered language comes from AGC metadata/URL markers, never a legacy local directory name.
_Avoid_: latest version, current version

**Citation Receipt**:
The in-app verification experience opened from a provenance-backed citation. Keeps the delivered claim and its source visible together, renders one physical PDF page at a time, draws a highlight only for a uniquely matched **Evidence Span**. Right-hand drawer on desktop; full-screen sheet on narrower screens.
_Avoid_: PDF link, source popup

**Receipt Document**:
An immutable, manifest-identified PDF snapshot — its bytes are exactly those used by one **Extraction Run**. Content-derived identity: Act, source language, full SHA-256. Byte size and page count also get checked, before enrichment, location, or delivery. Multiple languages and historical versions may exist for one Act.
_Avoid_: latest PDF, remote PDF, Official Source Link

**Extraction Run**:
A deterministic extraction of one **Receipt Document**, identified by document identity, extractor/version, and configuration hash. Owns a chunk-set hash and a hash-verified word-coordinate sidecar. Retrieval chunks carry its `document_id`, `extraction_id`, content hash, page bounds.

**Active Corpus Mapping**:
The reversible pointer from one `(Act, language)` pair to a ready **Receipt Document** and **Extraction Run**. New bytes get registered and shadow-ingested before this pointer moves; the prior mapping stays in activation history for rollback.

**Corpus Rollout**:
The idempotent operator workflow: prepares missing immutable assets, applies the provenance migration, registers identities, ingests only absent **Extraction Runs**, advances **Active Corpus Mappings** only for verified successes. Normally one resumable command. The individual lifecycle commands are recovery controls, not required setup steps.

**Evidence Span**:
A legal claim from the delivered draft, plus one short, contiguous supporting quote. Exists only after application code independently confirms four things: the supported label, the cited Act/section, the claim occurring in the draft, the quote occurring in the retrieved chunk. Partial, unsupported, hallucinated, overlong, and duplicate spans get excluded.
_Avoid_: model highlight, source chunk

**Locator Result**:
The outcome of strict matching for an **Evidence Span** against the exact **Extraction Run** coordinate sidecar. One of: `matched`, `not_found`, `ambiguous`. Only a unique, contiguous, normalized-token match produces page-grouped rectangles. The citation `page_number` is just the fallback section-start page — not proof evidence occurs there.

**Official Source Link**:
The citation's remote AGC `pdf_url`, offered separately as "Check latest on AGC". Lets a practitioner inspect the government portal's current remote source. Not the **Receipt Document** — its bytes never assert an exact highlight.

**Statutory Reference Graph**:
An offline, deterministic index of literal statutory cross-references, for one immutable **Receipt Document**. Records readable stable provision identities, document-qualified version identities, exact half-open evidence offsets, physical receipt provenance, resolved one-hop edges, unresolved reason codes. Never infers a cross-Act snapshot, calls an API to resolve ambiguity, or alters retrieval chunks.
_Avoid_: citation graph (it's a statutory-text index, not answer provenance)

**Reference Graph Audit Candidate**:
A build artifact held under the graph snapshot's `.work` directory until a human checks every proposed edge against the immutable **Receipt Document**. Only a complete approved/rejected decision set produces a promoted graph; rejected candidates stay unresolved.

**Snapshot Catalog**:
The strict chronological list of consolidated REPRINT and REPRINT ONLINE timeline observations eligible for an Act's reference graph. Cataloguing is network-free. Dates label observed snapshots — never described as exact amendment-effective dates.

**Logical Reference**:
A comparison identity built from readable source and target provision identities, reference kind, relationship, normalized literal wording. Excludes PDF offsets and edge IDs. Repeated identical occurrences kept with deterministic ordinals; a wording change is one removed plus one added reference.

**Reference Graph Comparison**:
A fixed-position overlay of the union of two independently audited, promoted one-hop neighborhoods, same Act and language. Reports only observed added, removed, and unchanged **Logical References**. Keeps each snapshot's evidence and receipt separate, makes no claim about when or why a difference arose.

**Reference Follow Operation**:
A selective internal **Retrieval Agent** operation. Starts only after an existing search/lookup establishes one unique, exact **Receipt Document** + **Extraction Run** anchor. Reads published edges from that anchor's promoted **Statutory Reference Graph**, scopes a section to its audited child provisions, orders deterministically, returns at most five direct outgoing/incoming edges — at most once per retrieval run. Never follows a target for a second hop, never exposes unresolved candidates, never expands a boundary node, never treats graph text/evidence as answerable citation content. Same-Act target text comes from the anchor's exact extraction. Cross-Act targets are version-neutral identities — their independently retrieved text keeps its own corpus provenance, no source-snapshot as-of claim. Missing graph/target data fails open.
_Avoid_: graph search, automatic traversal, graph citation

**Timeline Entry**:
A dated version event for an Act: ORIGINAL, REPRINT, REPRINT ONLINE, or AMENDMENTS. Stored in the `timeline` array of each act metadata file.

**Case Law**:
Court judgments (decisions). Not in scope for v1. Planned for v2 via CommonLII (commonlii.org/my/).
_Avoid_: cases, judgments (until v2 is scoped)

**Legal Research Query**:
A practitioner's question with legal-research substance — statute lookup ("what does Section X of Act Y say?"), topical ("which Acts govern data privacy in Malaysia?"), or comparative. Not a request for legal advice about a specific situation. Not every input qualifies: a **Conversational Turn** carries no legal substance and is handled separately.

**Conversational Turn**:
A message with no legal-research substance — a greeting, self-introduction or name, thanks, small talk, or a meta question about the assistant ("what can you do?", "how does this work?"). The router classifies these as `conversational` only when *unambiguously* social or meta; anything with legal substance stays on the legal path. Answered directly with a short, warm reply — bypasses retrieval and the **Supervisor Rules**, no citations, no disclaimer. Still mirrors the query language, reads **Conversation History** (so the agent can recall a name given earlier), and reads recalled **Semantic Memory** — the same `recall` step that precedes the synthesiser runs before it too, so saved preferences can personalise the reply. Also *writes* to Semantic Memory: a self-introduction ("I'm a software engineer exploring legal tech") is where a practitioner's own background surfaces, worth remembering as a durable fact (ADR 0012). Only the practitioner's *own* professional identity gets stored this way — confidential client/matter facts and sensitive personal life excluded by construction.

**Conversation History**:
The prior turns in the same thread, passed as a list of user/assistant messages. Used to interpret follow-ups like "what about criminal cases?". For v1, the most recent turns are kept within a token budget: trimmed in whole user+assistant turns, never split mid-turn, most recent turn always kept. The stored assistant turn is the *delivered* response — including the safe fallback when a turn is fail-closed — so history always mirrors what the practitioner actually received, never a rejected draft.

**Standalone Query**:
The history-resolved, self-contained version of a follow-up **Legal Research Query**. A short or elliptical follow-up ("what about criminal cases?", "and in Bahasa?") gets rewritten into a query that carries forward the act, topic, or section from **Conversation History**, so it can be retrieved on its own. Used only for retrieval — never shown to the practitioner, never recorded in **Conversation History** (which always stores what the practitioner actually typed).
_Avoid_: expanded query, resolved query

**Retrieval Agent**:
The tool-calling form of the retrieval step (flag `AGENTIC_RETRIEVAL`, ADR 0013). Rather than a fixed "exact-lookup-else-vector-search" dispatch, an LLM binds two **Retrieval Tools** — `search_statutes` (semantic search) and `lookup_section` (exact section lookup) — and decides which to call, with what arguments, and whether to search again on weak results. The independently default-off `FOLLOW_REFERENCES_ENABLED` flag adds `follow_references` and its conditional prompt; off, the original two-tool surface and prompt stay unchanged. This internal flag needs the Retrieval Agent, not the public `REFERENCE_GRAPH_ENABLED` flag. A deterministic intent gate plus an invocation-scoped/state guard enforce the **Reference Follow Operation**, even on a bad model choice or parallel duplicate calls. Gathers sources only — never drafts the answer — and **fails open** to the deterministic retriever, so it can never return less than the proven path.
_Avoid_: calling it "the retriever" without qualification (that name is the deterministic node); "search agent"

**Re-retrieval**:
The retry behaviour where an **Evidence Violation** (a citation absent from the retrieved sources, or a grounding check flagging an unsupported claim) sends the turn back to the **Retrieval Agent** with feedback about the gap, instead of re-drafting against the same sources. A policy/phrasing violation still re-drafts. Bounded by the same single-retry budget — one *smarter* retry, not more loops. Only engages with `AGENTIC_RETRIEVAL` on.
_Avoid_: "retry" unqualified (there are two kinds — re-draft vs re-retrieve)

**Practitioner**:
The human using the assistant across research threads. Identified by a **User Id** — a UUID generated and persisted in the practitioner's browser, sent with every query. Weak, per-browser identity (no authentication in v1) — the scope key that lets **Semantic Memory** outlive a single thread.
_Avoid_: account, session (a session is one thread; a **Practitioner** spans many)

**Semantic Memory**:
Durable facts about a **Practitioner** that persist across research threads — their own professional background, response-language preference, citation/format style, practice-area focus, frequently-referenced **Acts**, recurring research topics. Stored in a cross-thread store namespaced by **User Id**, extracted in the background after a turn (legal or conversational), read back to personalise later turns. Distinct from **Conversation History**, which is one thread's transcript. Confidential client or matter facts are **never** stored here.
_Avoid_: long-term memory (ambiguous — name the tier), profile (that's one part of it)

**Recurring Topic**:
A research subject a **Practitioner** returns to across threads (e.g. "data-breach penalties", "unfair dismissal"). Held as a growing collection in **Semantic Memory**, used to bias retrieval. A one-off **Legal Research Query** is not on its own a **Recurring Topic**.

**Working Memory**:
The slice of context actually placed in a prompt for the current turn — the token-budget-trimmed **Conversation History** plus any recalled **Semantic Memory** facts. Derived at read time, never stored.
_Avoid_: context window (that's the model limit, not this projection)

**Legal Advice** _(out of scope)_:
A recommendation about what a specific person should do in a specific legal situation. The agent must never produce this — it hands off to a human lawyer instead.

## Relationships

- An **Act** has one or more **Timeline Entries**
- An **Act** may have multiple immutable **Receipt Documents** across languages and historical versions
- An **Active Corpus Mapping** selects one ready **Extraction Run** per Act/language without deleting history
- A provenance-backed citation may carry zero or more validated **Evidence Spans** and opens one shared **Citation Receipt**
- A **Locator Result** maps one selected **Evidence Span** to physical rectangles in the **Receipt Document**; uncertainty maps to no rectangles
- The **Official Source Link** stays separate from the **Receipt Document** because remote bytes and pagination can change
- A **Receipt Document** may have zero or one promoted **Statutory Reference Graph** per document version; a graph stays independent from retrieval and chat availability
- A **Reference Follow Operation** may consume one available promoted graph without exposing the public graph API, but only exact corpus chunks — not graph text — can become answer/citation sources
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
3. **Hedging required** — response must include a disclaimer that it's not a substitute for professional legal advice
4. **Escalation trigger** — if the query contains "my client", "I have been charged", "am I liable", route to human hand-off before retrieval starts

## Query Language Behaviour

Malaysian law practitioners code-switch heavily — mixing BM and English in a single query ("tolong check Section 14 Evidence Act"). The system may retrieve English and BM chunks together. A citation and quotation keep the registered source language; BM-only Acts 144, 152, 194, 220, 228, and 230 must never be relabeled as English. Response prose mirrors the dominant language of the query.

## Interruption: two distinct mechanisms

A turn can stop mid-flight for two unrelated reasons, kept separate by the system:

- **Clarification** is *graph-initiated*. When a **Legal Research Query** is un-actionable as written — most often a section number with no Act named — the router routes to the `clarify` node, which calls LangGraph's `interrupt()`. The turn suspends on its checkpoint, an `interrupt` SSE event carries the question to the practitioner, and the graph resumes only on `POST /resume { thread_id, value }`. The answer **merges** with the original query into one self-contained query — so retrieval sees the full intent, not the bare answer — and gets re-classified. A turn asks at most one clarifying question. See ADR 0015.
- **Barge-in** is *user-initiated* cancellation — the practitioner presses Stop/Esc (`POST /cancel`, or sends a new prompt on the same thread). Aborts the in-flight run; nothing gets written. See ADR 0014.

Both rely on the same `thread_id` checkpoint continuation, but one *pauses for input* while the other *aborts the run* — they never share a code path. A **Conversational Turn** and an **escalate** hand-off are separate short-circuits again: neither pauses nor cancels, they just skip the pipeline.

## Observability

When `LANGSMITH_TRACING` is on, every turn traces to LangSmith. Beyond the free node-level trace, the query lifecycle (`agent/query_lifecycle.py`) labels each run — `run_name=legal_query`, a `source` (`api` vs `eval`), active feature flags, `user_id`/`thread_id` metadata — and posts the turn's quality outcome as run **feedback** (`agent/observability.py`): `passed`, violation/citation counts, `retry_count`, `fallback_delivered`, `escalated`, categorical `query_type`. Reference following adds only numeric, low-cardinality feedback: calls, skipped/disabled/unavailable outcomes, edges considered/returned, targets looked up/resolved/failed, boundary targets, fail-open occurrences. Never logs provision text, graph evidence phrases, source content, or query text. These are the same signals the **Supervisor Rules** and evidence checks compute, so groundedness and pass-rate become chartable over time. Fail-open, off the hot path — never changes or delays a **Legal Research Query** response.

Receipt delivery separately emits structured availability, integrity, delivery, and locator-outcome events. The browser reports only allowlisted render/request failure metadata; claims, quotes, and source URLs are never included.

## Evaluation dashboard

An **Eval Run** is a single, explicitly selected slice of the hand-validated eval dataset — not prompt-version history. The developer dashboard separates two views:

- **Coverage** is static metadata derived from `evals/dataset.json`: case counts, smoke coverage, policy balance, scenarios, advisory gap flags. Available without a database.
- **Effectiveness** is the result of a live **Eval Run**: deterministic L1 assertions, then the LLM judge only when L1 passes, pass rates grouped by scenario for that run.

Live runs execute one at a time, in an isolated subprocess, against `EVALS_DATABASE_URL` — never the application's `DATABASE_URL`. Before starting, the API checks that every citation-applicable Act/section pair exists in the dedicated eval corpus. Streams each completed case as JSONL-backed SSE, terminates the subprocess on explicit cancellation or browser disconnect. `CHECKPOINTER=memory` is forced, since every eval case is a fresh single-turn thread — the eval database only needs to store curated `chunks`.

The API surface is `GET /evals/coverage`, `POST /evals/run`, `POST /evals/cancel`, and `GET /evals/results`. The standalone Next.js `/evals` route is exposed only when `NEXT_PUBLIC_EVALS=1` at build time.

## Flagged ambiguities

- "legislation" was used loosely to mean both Acts and Subsidiary Legislation — resolved: use **Act** for statutes and **Subsidiary Legislation** for P.U. instruments.
- "case" was used to mean both court judgments and use-cases — resolved: **Case Law** for court judgments only.
