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
A practitioner's question directed at the agent. May be statute lookup ("what does Section X of Act Y say?"), topical ("which Acts govern data privacy in Malaysia?"), or comparative. Does NOT include requests for legal advice about a specific situation.

**Conversation History**:
The prior turns in the same thread, passed as a list of user/assistant messages. Used to interpret follow-up questions like "what about criminal cases?". For v1, the most recent turns are kept within a token budget (trimmed in whole user+assistant turns, never split mid-turn; the most recent turn is always kept). The stored assistant turn is the *delivered* response — including the safe fallback when a turn is fail-closed — so history always mirrors what the practitioner actually received, never a rejected draft.

**Standalone Query**:
The history-resolved, self-contained version of a follow-up **Legal Research Query**. A short or elliptical follow-up ("what about criminal cases?", "and in Bahasa?") is rewritten into a query that carries forward the act, topic, or section from **Conversation History** so it can be retrieved on its own. Used only for retrieval; it is never shown to the practitioner and never recorded in **Conversation History** (which always stores what the practitioner actually typed).
_Avoid_: expanded query, resolved query

**Legal Advice** _(out of scope)_:
A recommendation about what a specific person should do in a specific legal situation. The agent must never produce this; it hands off to a human lawyer instead.

## Relationships

- An **Act** has one or more **Timeline Entries**
- An **Act** may have zero or more **Subsidiary Legislation** items
- The most recent **Reprint** Timeline Entry is the canonical text used for ingestion
- A **Legal Research Query** is answered using **Acts** (v1) and eventually **Case Law** (v2)

## Example dialogue

> **Practitioner:** "What are the penalties under the Personal Data Protection Act?"
> **Agent:** Retrieves the relevant sections from the PDPA Reprint, cites the section numbers, and summarises — but does not advise whether a specific data breach constitutes a violation.

## Supervisor Rules

The agent enforces these constraints on every response before output:

1. **No advice on specific facts** — response must not contain "you should", "you must", "in your case", "I recommend"
2. **Citation required** — every legal claim must cite "Section X of Act Y"
3. **Hedging required** — response must include a disclaimer that it is not a substitute for professional legal advice
4. **Escalation trigger** — if the query contains "my client", "I have been charged", "am I liable", route to human hand-off before retrieval starts

## Query Language Behaviour

Malaysian law practitioners code-switch heavily — mixing BM and English in a single query ("tolong check Section 14 Evidence Act"). Language detection on code-switched queries is unreliable. The system retrieves from both English and BM chunks simultaneously. Cited statute text is always English (the authoritative court version). Response prose mirrors the dominant language of the query.

**v1 pilot corpus is English-only.** BM and code-switched queries still work via cross-lingual embedding similarity, with somewhat degraded accuracy for BM-heavy queries. BM corpus is added before the public write-up, at which point retrieval accuracy improvement is measured as a before/after eval.

## Flagged ambiguities

- "legislation" was used loosely to mean both Acts and Subsidiary Legislation — resolved: use **Act** for statutes and **Subsidiary Legislation** for P.U. instruments.
- "case" was used to mean both court judgments and use-cases — resolved: **Case Law** for court judgments only.
