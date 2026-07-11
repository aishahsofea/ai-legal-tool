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
A consolidated version of an Act that incorporates all amendments up to a given date. The `latest_reprint_pdf` field in the metadata is the canonical current English text of the Act. A corresponding BM reprint is also fetched where available.
_Avoid_: latest version, current version

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

Malaysian law practitioners code-switch heavily — mixing BM and English in a single query ("tolong check Section 14 Evidence Act"). Language detection on code-switched queries is unreliable. The system retrieves from both English and BM chunks simultaneously. Cited statute text is always English (the authoritative court version). Response prose mirrors the dominant language of the query.

**v1 pilot corpus is English-only.** BM and code-switched queries still work via cross-lingual embedding similarity, with somewhat degraded accuracy for BM-heavy queries. BM corpus is added before the public write-up, at which point retrieval accuracy improvement is measured as a before/after eval.

## Flagged ambiguities

- "legislation" was used loosely to mean both Acts and Subsidiary Legislation — resolved: use **Act** for statutes and **Subsidiary Legislation** for P.U. instruments.
- "case" was used to mean both court judgments and use-cases — resolved: **Case Law** for court judgments only.
