# Commentary is a second source class, never a citation

Date: 2026-09-19

ADR 0001 scoped v1 to legislation only, reasoning about CommonLII's robots.txt for case law.
`#56` asks for something else: an allowlisted web search that reaches practitioner commentary
— firm alerts, interpretation of amendments — for background material the corpus was never
going to carry. This ADR is the decision `#56`'s own Sequence asks for before any code: a search
result is a second kind of thing, called commentary, and no validation gate can mistake it for a
citation.

It extends ADR 0011 one step further: check structured data, not text shape. `citation_validator_node`
already treats `citations` as the only source of truth for presence (`agent/nodes/citation_validator.py:54`)
and reality (`:60`); this ADR applies the same discipline to a new kind of thing arriving at the
same node graph.

It also settles a design question `#56`'s issue thread left open: what stops a commentary-informed
sentence in the draft from tripping `grounding_check`'s claim-support judge? That trip burns every
retry to `agent/query_policy.py`'s `FINAL_FAILURE_RESPONSE` (`:68-69`). See Decisions.

Phase 0 (comment on `#56`, 2026-09-19) settled the allowlist this ADR depends on. Skrine and Shearn
Delamore publish real, dated, section-citing commentary as HTML, with no receipt path available to
it. The two regulator sources checked — LHDN and Bank Negara — collapse straight back to PDF, the
same shape as an Act reprint. The gap is real, and narrow enough to build against without guessing.

This does not reopen ADR 0001's case-law exclusion — CommonLII's robots.txt reasoning is untouched.
Nor does it put commentary text into pgvector or the corpus pipeline. That pipeline exists for
immutable, citable bytes; commentary is neither, on purpose.

## Decisions

- **Commentary is structurally incapable of being a citation.** A `CommentaryNote` (Phase 2's
  `agent/state.py`) carries a URL, title, publisher, snippet, and dates. It has no bytes, no page,
  and no word coordinate. Those are the three things `ExtractionRun.from_dict` requires before a
  run can reach `ready` (`corpus/models.py:124`). They're also what `locate_evidence` requires
  before a quote can reach `matched` (`citation_receipts/locator.py:196`). A `CommentaryNote` never
  becomes a `Citation`, is never appended to `retrieved_chunks`, and never carries a `receipt`.
  This is a type-level guarantee, not a policy one: nothing that produces a `CommentaryNote` has
  the fields a citation needs, so there is no check to bypass.

- **The allowlist is the trust boundary, and it stays short.** `search_commentary` (Phase 3) may
  only return results from a fixed set of publisher domains, read from configuration. A domain
  outside the list is dropped before the model ever sees it, and a counter records it.
  `grounding_check_node` already uses this same fail-closed-and-count-it shape for its own honesty
  check: `agent/nodes/grounding_check.py:264-265` records a skip rather than pretending the check
  ran. Phase 0's draft list — `skrine.com`, `shearndelamore.com`, `themalaysianlawyer.com` — gates
  this build. `CONTRIBUTING.md` owns the list an operator actually runs, and can grow or shrink it
  without touching code.

- **ADR 0016's receipt guarantee is unchanged, because commentary never enters its scope.**
  ADR 0016 makes a Citation Receipt provable back to one exact SHA-256 and one exact extraction
  run. Nothing in this ADR touches `corpus/`, the registry, or activation. A commentary note is not
  a lesser receipt or a receipt-in-progress; it is a kind of evidence ADR 0016's guarantee was never
  asked to cover, the same way a practitioner's own recollection isn't.

- **The grounding judge is scoped to sentences the draft itself attributes to a cited section;
  unattributed prose is not a claim it checks.** `grounding_check_node`'s judge already extracts
  "every sentence or clause... that makes a legal claim" from the whole draft and requires each one
  to name the `cited_act_number`/`cited_section_number` it rests on (`agent/nodes/grounding_check.py:34-45`).
  Its system prompt already carries a list of text the judge ignores outright — disclaimers,
  transitions, headings, source labels (`:101`). A background sentence drawn from a commentary note
  reads as a legal claim by that same test today. It finds no matching citation and is labelled
  `unsupported` (`:187`). That label appends to `evidence_violations` (`:194`) and routes to
  `retry_retrieve` rather than a re-draft. On every turn that actually uses commentary, this burns
  every retry to `FINAL_FAILURE_RESPONSE`. The fix extends the existing ignore-list instead of
  adding a mechanism: a sentence with no attribution to a cited section is background, not a claim,
  and is never extracted for judgment — commentary-informed or not. This is also what keeps a
  commentary note from ever being labelled `supported` for free. `_collect_cited_sources` (`:104`)
  builds its source list only from `state["citations"]`, and nothing in Phase 3 changes that. So
  the judge is never handed commentary text to support a claim with in the first place. Phase 5
  writes the prompt change and proves it with a flag-on turn that completes without reaching
  `MAX_RETRIES`.

- **This amends ADR 0001's scope, not its reasoning.** v1's legislation-only boundary now has one
  carved-out exception — web commentary — made by this ADR, rather than by quietly stretching what
  "legislation" covers.

## Considered options

- **Confine commentary-informed prose to a block the grounding judge never reads, instead of
  scoping the judge.** Rejected for this phase. It solves the same failure but needs a second
  draft-text field threaded through `agent/state.py`, `delivered_response` (`agent/query_policy.py:61-70`),
  history recording, and the SSE `response` event — none of which Phase 5's or Phase 6's file lists
  touch. Scoping the judge's own claim-extraction step is a prompt change inside the node that
  already owns this decision, with nothing new for `delivered_response` or the frontend to learn
  about. Revisit if the attribution-marker heuristic proves unreliable — Phase 5's flag-on eval is
  what would show that.

- **Let a commentary note satisfy citation presence when no statute citation exists, so a
  commentary-only turn doesn't fail closed.** Rejected. This is the one shortcut the whole design
  exists to refuse. A Citation Receipt lets a practitioner open the drawer and see the exact PDF
  bytes under a claim; a search result can never offer that, so a turn that can only produce one
  should still fail closed, the same way a turn with nothing at all does today.

- **Skip the allowlist and rank search results by a domain-reputation heuristic instead.** Rejected.
  A ranked heuristic is not a boundary — it degrades under an adversarial or merely low-quality
  result instead of refusing it outright, and there is no one list an operator or reviewer can read
  to know what it currently trusts.

## Consequences

- `docs/adr/0001-v1-legislation-only-data-source.md` stays unedited. Its legislation-only scope is
  now qualified by this ADR rather than rewritten, the same way ADR 0002 stayed unedited under
  ADR 0018 and ADR 0019.
- Phases 2 onward build state, tool, and prompt changes against a settled type boundary and a
  settled grounding rule, without re-litigating either in review.
- With `WEB_COMMENTARY_ENABLED` unset, none of this is reachable — no new node, edge, or populated
  field — per Phase 2's reset in `_start_turn`. Rollback is the flag, not a revert.
- Phase 0's three domains are a draft, not a commitment. `CONTRIBUTING.md`'s allowlist, from Phase 2
  onward, is what an operator and a future reader should trust as current.
- Case law stays out of scope. Nothing here reopens CommonLII or ADR 0001's robots.txt reasoning.

## Related

- ADR 0001 — v1 legislation-only scope; amended here to carve out web commentary as a second
  source class, its case-law reasoning otherwise untouched.
- ADR 0011 — structured citation validation; this ADR extends the same structured-data-not-prose
  principle to a second, adjacent gate.
- ADR 0016 — immutable corpus provenance; unaffected, per Decisions above.
- `#56` — the issue this ADR is part of; see the opening paragraphs for Phase 0's role in it.
- `#119` — the shared web-search transport `search_commentary` (Phase 3) will sit on top of.
