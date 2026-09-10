# Cite the English sibling when a BM chunk wins retrieval

Date: 2026-09-09

ADR 0004 set two rules. First: retrieval searches `en` and `bm` chunks together with no language pre-filter, because practitioners code-switch and language detection is unreliable. Second: cited text is always English, because English is the authoritative version in Malaysian courts. These two rules never collided while the corpus was English-only.

The BM corpus has since been registered, extracted, and shadow-ingested, but not yet activated for retrieval — activation is the reversible per-`(Act, language)` pointer ADR 0016 defines. Flipping that pointer puts both rules in play at once: once a BM chunk can win retrieval, "cited text is always English" needs a mechanism, not just a sentence — supplied below, extending ADR 0004 rather than overturning it.

ADR 0016 sharpens the stakes. Receipts are keyed per `(Act, language)`, and the pilot's receipt-view design deliberately left BM Receipt Documents out of scope. A BM chunk that wins retrieval has no receipt to offer. Without a rule, every BM-won citation silently degrades — with no error, no test failure, nothing to notice — and the Citation Receipt feature quietly stops working the moment BM activates.

## Decisions

- **Resolve at the retrieval boundary, not after.** When a chunk in a retrieval result is `bm`, look for its English sibling using the same `(act_number, section_number)` key ADR 0004 already uses to link chunks across languages. Do this at the one point both retrieval paths converge: the deterministic retriever's return value, and the agentic retriever's final chunk list. That way synthesis, citation validation, and grounding keep operating on English chunks exactly as they do today — nothing downstream of retrieval changes.
- **Resolution is dedupe, then fetch.** First, drop a `bm` row when an `en` row for the same `(act, section)` already made the result set. Second, for any `bm` row still standing, run one targeted exact-match lookup for its English sibling — the same act+section exact-lookup path already used for statute-number queries, not a new embedding search. If that lookup returns nothing, there is no English sibling; fall through to the next decision.
- **No English sibling is one functional outcome, not a hardcoded Act list.** Whether the reason is one of the six BM-only Acts (CONTEXT.md's Query Language Behaviour section names them) or a bilingual Act with a temporary corpus gap, the result is treated identically: quote the BM text as retrieved, and mark the citation's language as `bm`. The six known Acts stay a documented fact, not a code branch — see Considered options below for why a hardcoded list was rejected.
- **Citations carry their own language.** The citation gains an explicit `language` field, set from whichever chunk backs it after resolution. Most citations resolve, so they get `"en"` — unchanged from today's user-visible behavior. Only a genuine no-sibling fallback gets `"bm"`. A practitioner (or the frontend) no longer has to infer non-authoritative source language from the prose; the citation states it.
- **Receipt behavior does not change.** A resolved citation carries an English chunk with an English document identity, so it goes through the exact receipt-attachment path that already exists — no special-casing required. A no-sibling fallback citation keeps today's existing fail-soft behavior: an unregistered document identity fails to resolve to a Receipt Document, so the citation ships with the Official Source Link only, exactly as any other unregistered document already does.
- **No new feature flag.** Per-`(Act, language)` activation (ADR 0016) is already the gate: a `bm` chunk cannot reach a result set at all until its `(Act, bm)` mapping is active. A second flag on top would create a reachable and strictly worse state — BM active, resolution off — which is the exact bug this ADR closes. If a specific Act's BM mapping misbehaves, the existing per-Act activation rollback is the correct lever, not a global switch.
- **Two counters, not a new tracing surface.** `bm_resolved_count` and `bm_only_fallback_count` — numeric, per-turn — join the existing low-cardinality observability feedback already used for citation and violation counts. Enough to confirm the mechanism is firing, or notice an unexpected Act leaking into the fallback bucket, without adding any content-bearing telemetry.

## Considered options

- **Never surface a BM win — keep today's pre-activation behavior indefinitely.** Rejected. Refusing to ever cite a BM-won hit defeats the point of activating the BM corpus, and leaves the six BM-only Acts permanently uncitable regardless of relevance.
- **Quote whatever chunk wins, in its own language, with no resolution.** Rejected. This silently reopens ADR 0004's "cited text is always English" rule for every bilingual Act, not just the six that genuinely have no English text.
- **Resolve inside the synthesiser, after the model has already picked its citations.** Rejected. The grounding check sources cited text from the retrieved-chunk list by `(act, section, document_id)`. If a citation's identity is swapped after the fact without also updating that list, grounding silently finds no source to check the claim against. The claim then passes not because it was verified, but because it was never looked at. Resolving upstream of both synthesis and grounding avoids this by construction, instead of coordinating fixes across three nodes.
- **Add a feature flag alongside per-Act activation.** Rejected — see Decisions above; it creates a reachable "BM active, unpatched" state.
- **Reopen BM Receipt Documents into pilot scope.** Rejected for this ADR. None of the five pilot Acts are BM-only, so pilot receipt behavior is unaffected either way; building BM receipt support now turns a documentation decision into a receipts-viewer feature project. Left as a plausible future item, not decided here.
- **Hardcode the six known BM-only Acts as the fallback trigger.** Rejected, for the same reason ADR 0016 rejected a static Act-number allowlist elsewhere: it can't adapt to corpus changes and needs manual upkeep. The functional check — sibling lookup returns nothing — subsumes it and also catches a genuine data gap on a bilingual Act.

## Consequences

- Retrieval gains one function applied at the deterministic and agentic node-output boundary: dedupe same-section `bm`/`en` duplicates, then fetch the English sibling for any `bm` chunk still standing (same exact-match lookup as Decisions above).
- The citation shape gains a `language` field. This is an additive API-contract change, so `README.md`, `CONTRIBUTING.md`, and `CONTEXT.md` get the one-line update alongside the implementation.
- `CONTEXT.md`'s Query Language Behaviour section is corrected. It currently reads "a citation and quotation keep the registered source language" — broadened past this ADR's predecessor without a decision record behind it. It is narrowed back to: English by default via sibling resolution, source-language quoting only for a genuine no-sibling case.
- The synthesiser's prompt, citation validation, and grounding check need no code changes. The synthesiser's existing bilingual instruction — quote in the source language, never relabel a BM-only source as English — already anticipates exactly this outcome; it had nothing upstream guaranteeing the assumption held until now.
- `bm_resolved_count` and `bm_only_fallback_count` are added to per-turn observability feedback.
- Retrieval takes on one additional lookup per surviving `bm` chunk — same exact-match path as Decisions above, no embedding call — an accepted, presumed-cheap cost, not something requiring a cap.
- BM Receipt Documents remain out of scope — unchanged fail-soft path, see Decisions above.

## Related

- ADR 0004 — bilingual retrieval and embedding strategy; this ADR extends its citation-language rule for the case the two together create.
- ADR 0016 — immutable corpus provenance; supplies the `(Act, language)` activation gate this ADR relies on instead of a new flag, and the receipt fail-soft path this ADR reuses unchanged.
- ADR 0011 — structured citation validation; the same structured-data-over-inferred-signal principle motivates putting `language` directly on the citation rather than leaving it to be inferred from prose.
- Agent hardening backlog — "Decide how to cite authoritative English text while answering in BM"; this ADR is that item.
