# Remember the practitioner's own background, extract it from conversational turns

Date: 2026-07-07

ADR 0010 scoped Semantic Memory to *how a practitioner likes to work and what they research* — response language, format/citation style, practice-area focus, frequently-referenced Acts, recurring topics — and confined extraction to the **legal path**. In practice that left an obvious gap: a practitioner introduces themselves ("I'm a software engineer exploring legal tech"), and the assistant forgets it, because a self-introduction is a **conversational** turn and conversational turns did not extract. When later asked "what's my profession?" — on a new thread, where only cross-thread Semantic Memory could carry the answer — the agent had nothing. This ADR extends 0010 (it does not overturn it) to store the practitioner's **own professional background** and to extract on conversational turns.

## Decisions

- **The practitioner's own background is in scope.** A new `background` field on `PractitionerProfile` captures the user's own professional identity/role/goal ("software engineer exploring legal tech", "in-house counsel", "law student"). This is deliberately the **user's own** identity, which is *not* the confidential client/matter data ADR 0010 excluded — that exclusion guarded privilege and retention obligations attached to **third parties**, and it stays fully in force. Sensitive personal life (health, family, finances, religion) is explicitly excluded too: professional background only.
- **Extraction now runs on conversational turns, not just legal ones.** Self-introductions arrive as small talk, so the write path had to open to `conversational`. It still excludes the empty/error state and `escalate` (a fixed hand-off with nothing durable to extract). This resolves the read/write asymmetry introduced when recall was first wired onto the conversational path — that turn could *use* memory but not *feed* it; now it does both.
- **The extractor still decides what is durable.** Opening the path does not mean every "hi" or "thanks" writes a fact. The LangMem extractor, steered by instructions, extracts nothing when a turn holds no durable fact. The wiring tests lock that the path *fires*; whether a given turn yields a fact is an eval concern, not a wiring one.
- **The profile is recalled deterministically, not by similarity.** The practitioner's own profile (background, language, format style) is *always* relevant framing, so recall fetches it by kind (`filter={"kind": "PractitionerProfile"}`) and merges it ahead of the query-ranked recurring topics — rather than letting it compete in the vector search, where "what is my profession?" could rank the profile below a closer-embedding topic and drop it out of the top-N. This is what turns "usually remembers" into "always surfaces, if it was captured." Recurring topics stay similarity-ranked; only they earn a pruner importance hit (the always-on profile must not skew that signal).
- **No new store, node, or API surface.** `background` rides the existing `PractitionerProfile` schema, so recall's schema-agnostic field renderer surfaces it with no change. The pruner's profile consolidation had to learn the new scalar (`_merge_profiles` rebuilt content from a hardcoded field list, which would otherwise have dropped `background` the moment a second profile appeared) — now covered by a test. The only other moving parts are the schema field, the extraction instructions, and the one `query_type` guard in `query_lifecycle`.

## Considered options

- **Keep background out; treat the ask as out-of-scope.** Rejected. The user's own identity is genuinely useful for framing replies and carries none of the third-party privilege risk that motivated the 0010 exclusion. Refusing it would be cargo-culting the privacy boundary past where its rationale applies.
- **Store background but keep extraction legal-only.** Rejected as non-functional: the turn where background is stated is almost always conversational, so a legal-only write path would add the field but never populate it.
- **A dedicated identity store / node separate from `PractitionerProfile`.** Deferred. More surface area for no pilot-stage benefit; background is a durable practitioner preference like any other and fits the existing profile.
- **Extract on every turn including `escalate`.** Rejected. Escalation is a fixed hand-off message; there is nothing durable to mine, and mining the user's escalation query risks pulling in exactly the matter-specific facts 0010 excludes.

## Consequences

- **Small talk now costs a background extraction.** With `SEMANTIC_MEMORY_EXTRACT=on`, every conversational turn schedules a background extraction (off the hot path, fail-open). At pilot volume this is acceptable; a length/heuristic gate is the obvious lever if it becomes noticeable. (Recall already runs per conversational turn as of the prior change.)
- **Broader extraction surface, same privacy guard.** The instructions now actively capture the user's own background while still excluding client/matter facts *and* sensitive personal life. The guard tests assert the exclusion language survives; behavioural privacy ("a client fact stores nothing") remains an eval concern.
- **Living docs updated.** `README.md`, `CONTEXT.md`, and `CONTRIBUTING.md` now describe conversational turns as part of the write path. ADR 0010 is left as-is (frozen record of the original scope).

## Related

- ADR 0010 — the memory lifecycle this extends; its client/matter exclusion is unchanged.
- ADR 0007 — recall/extraction must respect the escalation boundary (raw query is never overwritten); `escalate` stays excluded from extraction here.
