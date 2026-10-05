# Malaysian Legal Research Assistant

An AI agent that helps Malaysian law practitioners research legislation and case law. The system retrieves and cites authoritative legal sources; it does not give legal advice and escalates to a human lawyer when needed.

## Language

### Acts and sources

**Act**:
A federal statute in the Laws of Malaysia (LOM) portal, lom.agc.gov.my.
_Avoid_: law, bill, legislation (too broad), statute

**Updated Act**:
An Act that has been amended. The LOM portal keeps its latest version. Has a numeric Act number.
_Avoid_: current Act, live Act

**Revised Act**:
An Act revised under the Revision of Laws Act 1968. Has a numeric Act number. The pipeline treats it the same as an Updated Act.

**Repealed Act**:
An Act no longer in force. Indexed for historical research, excluded from the main knowledge base by default.

**Subsidiary Legislation**:
Regulations, rules, or orders made under an Act. Governed by the parent Act.
- Referenced by P.U. number, e.g. P.U. (A) 49/2014.

_Avoid_: sub-act, regulations (alone)

**Reprint**:
A consolidated version of an Act, with amendments up to a given date.
- The scraper picks `latest_reprint_pdf` as the canonical source. It may be English or BM.
- Its language comes from AGC metadata or URL markers, never a legacy local directory name.

_Avoid_: latest version, current version

**Case Law**:
Court judgments. Not in scope for v1. Planned for v2 via CommonLII (commonlii.org/my/).
_Avoid_: cases, judgments (until v2 is scoped)

**Legal Advice** _(out of scope)_:
A recommendation about what a specific person should do in a specific legal situation. The agent must never give this. It hands off to a human lawyer.

### Document structure

**Division**:
One run of numbering inside an Act. The body is one division. Each schedule at the back is another, and so is the list of amendments.
- Every chunk has one division value: `body`, or the heading as the Act prints it.
- Schedules restart at paragraph 1, so a chunk's real identity is its **Path**.

_Avoid_: part, chapter (those subdivide the body and share its numbering)

**Path**:
A chunk's structural identifier inside its **Division**. It replaces `(division, section_number)`.
- `s.<n>`: a body section.
- `sched.<k>`: a schedule's own content, with no numbered item.
- `sched.<k>/para.<n>` or `sched.<k>/art.<n>`: one item of that schedule.
- `k` is the schedule's position in the Act, not the printed ordinal word (`"FIRST"`, `"PERTAMA"`). It works with no ordinal word.
- `section_number` is set only for a body chunk.

_Avoid_: section number (alone) — a schedule paragraph can share a body section's number

### Provenance and citation receipts

**Receipt Document**:
An immutable, manifest-identified PDF snapshot. Its bytes are exactly those one **Extraction Run** used.
- Identity is content-derived: Act, source language, full SHA-256. Byte size and page count are checked too, before enrichment, location, or delivery.
- One Act may have several, across languages and versions.

_Avoid_: latest PDF, remote PDF, Official Source Link

**Extraction Run**:
A deterministic extraction of one **Receipt Document**. Identified by document identity, extractor/version, and configuration hash.
- Owns a chunk-set hash and a hash-verified word-coordinate sidecar.
- Retrieval chunks carry its `document_id`, `extraction_id`, content hash, and page bounds.
- Text comes from the Receipt Document's own text layer. A scanned Receipt Document uses OCR under the same identity and reproducibility guarantee (ADR 0019).

**Active Corpus Mapping**:
The reversible pointer from one `(Act, language)` pair to a ready **Receipt Document** and **Extraction Run**.
- New bytes are registered and shadow-ingested before the pointer moves.
- The prior mapping stays in activation history for rollback.

**Corpus Rollout**:
The idempotent operator workflow, normally one resumable command. Steps:
- Prepare missing immutable assets.
- Apply the provenance migration and register identities.
- Ingest only absent **Extraction Runs**.
- Advance **Active Corpus Mappings** only for verified successes.

The individual lifecycle commands are recovery controls, not required setup steps.

**Evidence Span**:
A legal claim from the delivered draft, plus one short, contiguous supporting quote.
- Exists only after application code confirms four things: the supported label, the cited Act/section, the claim occurring in the draft, the quote occurring in the retrieved chunk.
- Partial, unsupported, hallucinated, overlong, and duplicate spans are excluded.

_Avoid_: model highlight, source chunk

**Locator Result**:
The outcome of strict matching an **Evidence Span** against the exact **Extraction Run** coordinate sidecar. One of `matched`, `not_found`, `ambiguous`.
- Only a unique, contiguous, normalized-token match produces page-grouped rectangles.
- The citation `page_number` is only the fallback section-start page. It does not prove the evidence is there.

**Citation Receipt**:
The in-app verification view opened from a provenance-backed citation.
- Keeps the delivered claim and its source visible together.
- Renders one physical PDF page at a time.
- Highlights only for a uniquely matched **Evidence Span**.
- Right-hand drawer on desktop, full-screen sheet on narrower screens.

_Avoid_: PDF link, source popup

**Official Source Link**:
The citation's remote AGC `pdf_url`, offered separately as "Check latest on AGC". Lets a practitioner inspect the government portal's current source.
- It is not the **Receipt Document**. Its bytes never assert an exact highlight.

**Commentary Note**:
Background material from an allowlisted web publisher. Carried on its own `commentary` channel. Never a citation, never appended to `retrieved_chunks`.
- Gated by `WEB_COMMENTARY_ENABLED` (ADR 0020); flag off means no behaviour change. See [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables).
- Has no bytes, page, or word coordinate, so it can never open a **Citation Receipt** or satisfy citation presence. A type-level guarantee, not a policy one.

_Avoid_: source (already means citation in the UI's SOURCE MAP / SOURCES USED), reference (already the **Statutory Reference Graph**'s vocabulary)

### Reference graph

**Statutory Reference Graph**:
An offline, deterministic index of literal statutory cross-references, for one immutable **Receipt Document**.
- Records stable provision identities, document-qualified version identities, exact half-open evidence offsets, receipt provenance, resolved one-hop edges, and unresolved reason codes.
- Never infers a cross-Act snapshot, calls an API to resolve ambiguity, or alters retrieval chunks.

_Avoid_: citation graph (it's a statutory-text index, not answer provenance)

**Reference Graph Audit Candidate**:
A build artifact under the graph snapshot's `.work` directory. It waits there until a human checks every proposed edge against the immutable **Receipt Document**.
- Only a complete approved/rejected decision set produces a promoted graph.
- Rejected candidates stay unresolved.

**Snapshot Catalog**:
The strict chronological list of consolidated REPRINT and REPRINT ONLINE timeline observations eligible for an Act's reference graph.
- Cataloguing is network-free.
- Dates label observed snapshots. They are never described as exact amendment-effective dates.

**Logical Reference**:
A comparison identity built from readable source and target provision identities, reference kind, relationship, and normalized literal wording.
- Excludes PDF offsets and edge IDs.
- Repeated identical occurrences are kept with deterministic ordinals.
- A wording change counts as one removed plus one added reference.

**Reference Graph Comparison**:
A fixed-position overlay of two independently audited, promoted one-hop neighborhoods, same Act and language.
- Reports only observed added, removed, and unchanged **Logical References**.
- Keeps each snapshot's evidence and receipt separate.
- Makes no claim about when or why a difference arose.

**Reference Follow Operation**:
A selective internal **Retrieval Agent** operation: one bounded hop through a promoted **Statutory Reference Graph**, taken only after search or lookup has found an exact anchor.
- Never a citation source itself. Same-Act text still comes from the anchor's own extraction. Cross-Act targets keep their own provenance.
- Missing graph or target data fails open.
- Edge cap, ordering, hop limit, and boundary handling: [CONTRIBUTING.md](CONTRIBUTING.md#statutory-reference-graph-operator-workflow).

_Avoid_: graph search, automatic traversal, graph citation

### Currency and timeline

**Timeline Entry**:
A dated version event for an Act: `ORIGINAL`, `REPRINT`, `REPRINT ONLINE`, `AMENDMENTS`, `REPEALED`, or `SUPERSEDED`.
- Stored in the `timeline` array of each act metadata file (`timeline_bm` for the Bahasa Malaysia page).

**Currency Label**:
A check attached to a citation after the answer is drafted. It says whether the cited Act was repealed or amended after we indexed it.
- The label comes from the Act's own **Timeline Entry** history, compared with the reprint date `data/pdfs/manifest.json` recorded at indexing. No search or model is involved.
- Gated by `CURRENCY_CHECK_ENABLED`. Flag off means no behaviour change.

Outcomes, checked in this order:

| Label | Meaning | Badge |
| --- | --- | --- |
| `repealed` | A `REPEALED` or `SUPERSEDED` entry exists. Wins regardless of dates. | yes |
| `superseded` | No repeal, but the latest `AMENDMENTS` entry postdates our reprint. | yes |
| `current_as_indexed` | Our reprint postdates every recorded amendment. | none |
| `unknown` | None of the above can be established: no manifest match, no amendment recorded at all, or a date that doesn't parse. | none |

Limits:
- No badge is not a guarantee. Do not read its absence as confirmation.
- The check is only as fresh as the metadata's `scraped_at`. A repeal or amendment gazetted since the last scrape is invisible to it.
- A same-date collision in the source page's markup (#67) can silently drop a Timeline Entry.
- `unknown` means "none recorded", never "verified current". `current_as_indexed` means "no amendment recorded after our reprint", never "confirmed unchanged".
- A **Repealed Act** excluded at scrape time never reaches this check. The check covers the opposite case: an Act that was current when indexed and was repealed or amended afterward. Nothing else in the pipeline flags that Act.

_Avoid_: repeal warning (a factual check against the timeline, not a heuristic), stale citation (says the Act moved, never that the cited section is wrong)

### Queries and retrieval

**Legal Research Query**:
A practitioner's question with legal-research substance: statute lookup ("what does Section X of Act Y say?"), topical ("which Acts govern data privacy in Malaysia?"), or comparative.
- Not a request for legal advice about a specific situation.
- A **Conversational Turn** has no legal substance and is handled separately.

**Conversational Turn**:
A message with no legal-research substance: a greeting, self-introduction, thanks, small talk, or a meta question about the assistant ("what can you do?").
- The router picks `conversational` only when the message is unambiguously social or meta. Anything with legal substance stays on the legal path. The Jev first pass and the LLM router both follow this rule.
- Gets a short, warm, direct reply in the query language. Skips retrieval and the **Supervisor Rules**. No citations, no disclaimer.
- Reads **Conversation History** and recalled **Semantic Memory**, via the same `recall` step as the synthesiser.
- Writes **Semantic Memory** from a self-introduction (ADR 0012). Only the practitioner's own professional identity is stored. Confidential client or matter facts and sensitive personal life are excluded by construction.

**Retrieval Agent**:
The tool-calling form of the retrieval step (flag `AGENTIC_RETRIEVAL`, ADR 0013). An LLM chooses the tool, its arguments, and whether to search again on weak results.
- Binds two **Retrieval Tools**: `search_statutes` (semantic search) and `lookup_section` (exact section lookup). A **Reference Follow Operation** may join them, gated by `FOLLOW_REFERENCES_ENABLED`.
- Gathers sources only. Never drafts the answer.
- **Fails open** to the deterministic retriever, so it never returns less than the proven path.
- Flags: [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables).

_Avoid_: "the retriever" without qualification (that name is the deterministic node), "search agent"

**Re-retrieval**:
The retry after an **Evidence Violation**: a citation absent from the retrieved sources, or a grounding check flagging an unsupported claim. The turn returns to the **Retrieval Agent** with feedback about the gap, rather than re-drafting on the same sources.
- A policy or phrasing violation still re-drafts.
- Same single-retry budget.
- Only with `AGENTIC_RETRIEVAL` on.

_Avoid_: "retry" unqualified (two kinds: re-draft and re-retrieve)

**Standalone Query**:
A follow-up **Legal Research Query** rewritten to stand on its own. A short follow-up ("what about criminal cases?", "and in Bahasa?") is rewritten to carry forward the act, topic, or section from **Conversation History**.
- Used only for retrieval.
- Never shown to the practitioner. Never recorded in Conversation History, which stores what the practitioner typed.

_Avoid_: expanded query, resolved query

### Conversation and memory

**Practitioner**:
The human using the assistant across research threads. Identified by a **User Id**: a UUID generated and kept in the practitioner's browser, sent with every query.
- Weak, per-browser identity (no authentication in v1).
- It is the scope key that lets **Semantic Memory** outlive one thread.

_Avoid_: account, session (a session is one thread; a **Practitioner** spans many)

**Conversation History**:
The prior turns in the same thread, passed as a list of user/assistant messages. Used to interpret follow-ups like "what about criminal cases?".
- v1 keeps the most recent turns within a token budget. Trimming drops whole user+assistant turns, never mid-turn, and always keeps the latest.
- The stored assistant turn is the delivered response, including the safe fallback when a turn fails closed. Never a rejected draft.

**Semantic Memory**:
Durable facts about a **Practitioner** that persist across threads.
- Holds: professional background, response-language preference, citation/format style, practice-area focus, frequently referenced **Acts**, recurring research topics.
- Stored per **User Id**, extracted in the background after any turn, read back to personalise later turns.
- Not **Conversation History**, which is one thread's transcript.
- Confidential client or matter facts are **never** stored here.

_Avoid_: long-term memory (ambiguous — name the tier), profile (that's one part of it)

**Recurring Topic**:
A research subject a **Practitioner** returns to across threads (e.g. "data-breach penalties", "unfair dismissal"). Held as a growing collection in **Semantic Memory**. Used to bias retrieval.
- A one-off **Legal Research Query** is not on its own a Recurring Topic.

**Working Memory**:
The slice of context placed in a prompt for the current turn: the token-budget-trimmed **Conversation History** plus any recalled **Semantic Memory** facts. Derived at read time, never stored.
_Avoid_: context window (that's the model limit, not this projection)

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

Malaysian law practitioners code-switch heavily, mixing BM and English in one query ("tolong check Section 14 Evidence Act"). The system may retrieve English and BM chunks together.

- When a BM chunk wins, it resolves to its English sibling by Act and section, for citation and quotation. English is the default source. Full rule: ADR 0017.
- Quoting stays in the registered source language only when no English sibling exists.
- BM-only Acts 144, 152, 194, 220, 228, and 230 must never be relabeled as English. The citation's own `language` field says so.
- Response prose mirrors the dominant language of the query.
- The eval suite scores what share of an answer is BM and fails a BM query answered mostly in English. See [CONTRIBUTING.md](CONTRIBUTING.md#scoring-bilingual-cases).

## Interruption: two distinct mechanisms

- **Clarification** is *graph-initiated*. If a **Legal Research Query** can't be acted on as written (most often a section number with no Act named), the router sends it to the `clarify` node. The node calls LangGraph's `interrupt()` and the turn suspends on its checkpoint.
  - An `interrupt` SSE event carries the question to the practitioner.
  - The graph resumes only on `POST /resume { thread_id, value }`.
  - The answer **merges** with the original query into one self-contained query, so retrieval sees the full intent, not the bare answer. Then it is re-classified.
  - A turn asks at most one clarifying question. See ADR 0015.
- **Barge-in** is *user-initiated* cancellation — the practitioner presses Stop/Esc (`POST /cancel`, or sends a new prompt on the same thread). Aborts the in-flight run; nothing gets written. See ADR 0014.

Both rely on the same `thread_id` checkpoint continuation, but one *pauses for input* and the other *aborts the run*. They never share a code path. A **Conversational Turn** and an **escalate** hand-off are separate again: neither pauses nor cancels, they skip the pipeline.

## Observability

With `LANGSMITH_TRACING` on, each turn traces to LangSmith and posts its quality outcome as run feedback. These are the same signals the **Supervisor Rules** and evidence checks compute.

- Feedback is always numeric and low-cardinality. It never holds provision text, evidence phrases, source content, or query text.
- It fails open and runs off the hot path. It never changes or delays a **Legal Research Query** response.
- Exact fields: [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables).

Receipt delivery separately emits structured availability, integrity, delivery, and locator-outcome events. The browser reports only allowlisted render/request failure metadata. Claims, quotes, and source URLs are never included.

## Evaluation dashboard

An **Eval Run** is one explicitly selected slice of the hand-validated eval dataset. It is not prompt-version history. The developer dashboard has two views:

- **Coverage** is static metadata from `evals/dataset.json`: case counts, smoke coverage, policy balance, scenarios, advisory gap flags. Needs no database.
- **Effectiveness** is the result of a live **Eval Run**: deterministic L1 assertions first, then the LLM judge only when L1 passes. Pass rates are grouped by scenario. A multi-part case is scored by **section recall**, the fraction of its expected statute sections the agent cited. See [CONTRIBUTING.md](CONTRIBUTING.md#scoring-multi-part-cases).

Live runs go one at a time, in an isolated subprocess, against `EVALS_DATABASE_URL`. They never touch the application's `DATABASE_URL`. Before starting, the API checks that every citation-applicable Act/section pair exists in the eval corpus. Each finished case streams as JSONL-backed SSE. The subprocess is terminated on explicit cancel or browser disconnect.

Endpoints, subprocess setup, and the `NEXT_PUBLIC_EVALS` build flag: [CONTRIBUTING.md](CONTRIBUTING.md#running-evals).

## Flagged ambiguities

- "legislation" was used loosely to mean both Acts and Subsidiary Legislation — resolved: use **Act** for statutes and **Subsidiary Legislation** for P.U. instruments.
- "case" was used to mean both court judgments and use-cases — resolved: **Case Law** for court judgments only.
