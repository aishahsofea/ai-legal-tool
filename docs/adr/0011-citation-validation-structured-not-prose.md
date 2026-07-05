# Citation validation over structured data, not prose regex

Date: 2026-07-05

Citation checking is split into **two concerns with two mechanisms**: citation *presence and reality* is a deterministic check over the synthesiser's **structured `citations`** list, and citation *support* (does the cited section actually back the claim) is an LLM grounding check. Neither concern is enforced by matching **citation format in prose** any longer. The prose-format regexes in `supervisor` and `citation_validator` are removed.

This reverses an earlier implicit design — that "at least one citation exists" could be asserted deterministically by pattern-matching the answer text — because that regex was silently calibrated to one model's citation style and broke on every phrasing it did not anticipate.

## Context

The supervisor enforced "Citation required" (Supervisor Rule 2) with `_CITATION_RE`, a regex over the draft prose requiring `Section X of [Act]` adjacency. The build log records it being re-tuned twice — once to accept `Code` as well as `Act`, once to accept a subsection-first form for non-Claude models — each time to fit a specific model's phrasing. It failed a third time on a factually correct GPT-4.1 answer that cited sections as `under section 379` and `(section 379)`, with the Act name earlier in the sentence: no `Section X of [Act]` substring, so Rule 2 fired, forced retries, and shipped the fail-closed fallback despite a correct answer.

`citation_validator` carried a second prose regex, `_PROSE_CITATION_RE`, to verify prose citations were mirrored by structured citations. It was brittle in the same way (English-only, adjacency-dependent), though it failed *safe*: an unparsed prose citation was simply not cross-checked, never falsely flagged.

By the time either regex ran, the graph already had a stronger signal. The synthesiser emits `citation_refs`, filtered to only sections that matched a retrieved chunk, and `grounding_check` already walks every claim and its cited section with an LLM. The deterministic prose matching was duplicating — brittlely — work the structured data and the grounding layer do better.

## Decisions

- **Citation presence is checked over structured `citations`, not prose.** A legal answer is "cited" when `state["citations"]` is non-empty. Because those entries are pre-filtered to real, retrieved sections, non-emptiness means "the model named at least one real section." This is model- and language-agnostic: it does not care whether the prose reads `Section 379 of the Penal Code`, `under section 379`, or `seksyen 379`.
- **Presence lives in `citation_validator`, not the supervisor.** All citation concerns — presence, reality (cited ∈ retrieved), and Act-metadata existence — now live in one node. `supervisor` keeps only prose-pattern policy rules that genuinely belong on the final draft: advice phrases, disclaimer, escalation. `_CITATION_RE` is deleted.
- **`_PROSE_CITATION_RE` and its prose-extraction helpers are deleted.** The prose↔structured *mirror* check is removed rather than reimplemented. Its core failure mode — the model dropping citations entirely (`citation_refs: []`) — is now caught more robustly by the presence check. The remaining failure modes (a prose citation that is hallucinated or omitted from the structured list) fall to `grounding_check`, which already verifies each load-bearing claim against its cited section.
- **`_normalise_section` stays.** It uses `re` to parse a section number out of a *structured field value* (`"90A(1)"` → `"90A"`). That is normalising known structured data, not sniffing free prose, and is not what this ADR removes.
- **Answer-level, not claim-level.** The deterministic rule guarantees the answer cites *something* real. Whether *each individual claim* is supported is owned by `grounding_check`. `CONTEXT.md` Rule 2 is corrected to state this explicitly, so the doc stops promising a claim-level guarantee the deterministic layer never provided.

## Considered options

- **Broaden `_CITATION_RE` again.** Rejected. This is the third failure of the same kind; each fix re-calibrates to the current model and the next model breaks it. The regex was "deterministic and testable" but silently coupled to Claude's citation style — a property that is a liability, not a guarantee.
- **Swap Rule 2 to a structured check but keep it in `supervisor`.** Rejected. Smaller diff, but leaves citation logic split across two nodes and the dead regex in place. Consolidating in `citation_validator` gives one node one job.
- **Keep the mirror check, reimplemented as an LLM check inside `citation_validator`.** Rejected for this change. `grounding_check` is already an LLM walking every claim and its citation; a second LLM mirror pass would duplicate it. Folded the coverage into grounding rather than adding a node.
- **Add a loose prose sanity token (`section|seksyen \d+`, no Act adjacency) as belt-and-suspenders.** Rejected. Re-imports prose matching to chase a failure mode (structured populated, prose visibly uncited) that does not occur in practice for a legal-answer model.

## Consequences

- **BM and code-switched answers get citation presence for free.** The deleted regexes were English-only; `seksyen X Akta Y` never matched. Structured presence is language-neutral, closing a latent wall that any BM-heavy query would have hit.
- **Cheaper failure path.** A presence failure is raised in `citation_validator`, which runs before `grounding_check`; the grounding node short-circuits when violations already exist, so an uncited answer no longer pays for the grounding LLM call before being sent to retry.
- **One narrow coverage gap, logged as a known limitation.** A section named in prose *in passing* — not carrying a distinct legal claim and absent from the structured list — is no longer flagged. `grounding_check` only reasons about load-bearing claims. Accepted as a narrow loss against the model/language robustness gained.
- **The "insufficient information" answer still fails closed.** A legitimately uncited "the retrieved sections don't cover this" answer has empty `citations`, so it violates presence, exhausts retries, and ships the safe fallback — unchanged from prior behaviour. Distinguishing "genuinely cannot answer" from "forgot to cite" needs an explicit synthesiser signal and is out of scope here.
- **Tests and living docs updated.** Supervisor/citation-validator tests that asserted on the prose regexes are updated; `README.md` / `CONTRIBUTING.md` are updated where they narrate the validation nodes. `docs/build-log.md` and prior ADRs are left as frozen records.

## Related

- ADR 0003 — Python / LangGraph agent runtime (the node graph this restructures a slice of).
- Agent hardening backlog — "Add deterministic citation validation against retrieved chunks and Act metadata instead of relying on prose regex alone"; this ADR is that item.
