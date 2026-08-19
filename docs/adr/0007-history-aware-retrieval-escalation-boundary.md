# History-aware retrieval via query rewriting; escalation stays on the raw query

To make follow-up questions retrievable, a `contextualize` node runs after the router. It rewrites an elliptical follow-up ("what about criminal cases?") into a **Standalone Query** — a self-contained question that carries forward the act, topic, or section from Conversation History. Retrieval (both exact statute lookup and vector search) runs on the Standalone Query. The practitioner's literal **raw query** stays untouched: it's the only thing recorded in Conversation History, and it's what the synthesiser answers. We chose query rewriting over embedding the query concatenated with history because our queries are short, code-switched, and ellipsis-heavy — concatenation would dilute the embedding instead of resolving the reference.

The escalation keyword check (Supervisor Rule 4 — "my client", "I have been charged", "am I liable") runs **only against the raw query**, before the contextualize node, and is deliberately *not* re-run on the Standalone Query.

## Considered Options

- **Re-check escalation on the Standalone Query.** Rejected. The Standalone Query legitimately stitches prior context back in. So a benign follow-up ("what's the maximum penalty?"), coming after an earlier sensitive turn, could resolve to text containing "charged" — and escalate on words the *system* reintroduced, not words the practitioner asked. That would make ordinary research follow-ups escalate constantly. It's the same fragility that already made us check escalation on the current query only, never the full transcript.
- **Escalate on the raw query only.** Chosen. Escalation exists to catch the practitioner *explicitly asking for advice in their own words* — that's exactly the raw query. A future reader might suspect this is a bypass. It isn't: the Standalone Query is retrieval-only and never shown to the practitioner, and the no-advice Supervisor Rules plus the disclaimer still guard the final answer.

## Consequences

- The escalation boundary is the raw query. Do **not** add a Standalone-Query escalation check to "tighten" safety — it reintroduces mass false escalation without closing a real gap.
- This decision is scoped to the English-only v1 pilot corpus. When the BM corpus lands, the rewrite's language behaviour (currently: preserve the user's language, no normalization) is worth revisiting as a retrieval before/after eval.
