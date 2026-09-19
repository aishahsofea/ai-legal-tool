# Implementation Plan: Commentary as a Non-Citable Source Class (#56)

> **Handoff doc.** Written for an implementing agent with no prior conversation context.
> Read it top to bottom before writing code. Every phase ends at a review gate — do not run
> two phases into one PR.

## 1. Goal

Let the agent reach an allowlisted set of web publishers for background material, and carry
what it finds as `commentary` — a source class no validation gate can mistake for statute.

After this change:

- A new `commentary` channel on `AgentState` holds web results. `citations` is untouched.
- A `search_commentary` tool writes that channel, and only that channel.
- `WEB_COMMENTARY_ENABLED` gates all of it. Off means no behaviour change at all — the full
  guarantee is in section 7.
- The SSE `response` event carries `commentary` next to `citations`, and the UI renders the two
  in visibly different blocks. A citation opens the receipt. A commentary note opens the
  publisher's site.

**Non-goals.** Case law — ADR 0001's CommonLII reasoning stands. Embedding commentary into
pgvector. Any change to `citation_receipts/`, `corpus/`, or the scraper. Reducing PDF downloads.
Choosing the final publisher list.

## 2. Background: why a search result can never be a citation

A Citation Receipt is defined by bytes. `ExtractionRun.from_dict` refuses to mark a run ready
without a coordinate sidecar (`corpus/models.py:124`), and `locate_evidence` draws a highlight
by matching normalised tokens against the words in that sidecar (`citation_receipts/locator.py:196`).
A search result has no bytes, no page, and no word coordinates. It can never reach `matched`.

Currency is the second reason. A firm briefing on Act 265 written in 2019 reads authoritative
and pre-dates the 2022 amendments. Search results carry a publication date at best. The AGC
timeline tells us which reprint is current, deterministically.

The gates already enforce the split, and this plan must not weaken them. ADR 0011 is why they
check structured data rather than prose:

- `citation_validator_node` reads `citations` and `retrieved_chunks` only. No structured
  citation at all is a violation (`agent/nodes/citation_validator.py:54`); a citation absent
  from the retrieved set is a violation (`:60`).
- `grounding_check_node` builds its source list from `citations` intersected with
  `retrieved_chunks` (`agent/nodes/grounding_check.py:104-139`).

So a turn carrying nothing but commentary still fails the presence check and still ships the
fail-closed fallback. That is correct and stays.

## 3. Naming

`Reference` was the name in the issue. It collides with the most heavily loaded term in this
codebase. Already taken:

- the Statutory Reference Graph, Logical Reference, Reference Graph Comparison and Reference
  Follow Operation definitions in `CONTEXT.md:64-81`
- `reference_graph/`, `agent/retrieval/reference_graph.py`, `api/reference_graph.py`
- the `reference_trace` / `reference_metrics` / `reference_followed` channels
- `FOLLOW_REFERENCES_ENABLED`

Use these instead:

| Issue text | Build this |
| --- | --- |
| `Reference` | `CommentaryNote` |
| `references` | `commentary` |
| `WEB_REFERENCES_ENABLED` | `WEB_COMMENTARY_ENABLED` |
| `agent/retrieval/web_references.py` | `agent/web_search.py` (#119, lands first) |
| the unnamed tool | `search_commentary` |

Do not name anything in the UI "source". That word already means citation there
(`SOURCE MAP`, `SOURCES USED` in `frontend/components/locus-workspace/Messages.tsx:38` and `:70`).

## 4. The prior art to copy

`follow_references` is this exact shape, already shipped. Read it before writing anything:

- An extra tool bound only when its flag is on, with its own system prompt variant —
  `agent/retrieval/agent.py:112-143`.
- Its own state channels, reset per turn in `_start_turn` (`agent/graph.py:113-132`) and on
  the re-retrieval path in `_retry_retrieve_node` (`agent/graph.py:80-91`).
- Its flag stamped onto trace metadata and tags — `agent/query_lifecycle.py:61-76`.
- Its result threaded onto `QueryResult` conditionally — `agent/query_lifecycle.py:163`.
- Fixed, zero-filled counters so a disabled or failed call still reports a full shape —
  `empty_reference_metrics`, `agent/retrieval/reference_graph.py:102-115`.

## 5. Implementation phases

Each phase is one branch and one PR referencing #56. Docs ride with the phase that changes the
env var, SSE event, or graph edge they document — CLAUDE.md requires it.

### Phase 0 — Draft the allowlist. No code.

The issue makes this a gate on whether to build at all, and its own reasoning shows why. The
sites carrying authoritative Malaysian statute all serve PDFs. If the trusted publisher list
collapses to those, the commentary gap is smaller than it looks and #56 should close unbuilt.

Deliverable is a comment on #56 — candidate publishers, one line of reasoning each, and a
build-or-close call.

Settle the contradiction at the same time. Sequence makes the list a gate; Out of scope calls it
an operator decision. The split: a draft list gates the build, the final list is operator config
in `CONTRIBUTING.md`.

**Verified by:** a human decision. Everything below is conditional on it.

### Phase 1 — ADR 0020. Docs only.

0018 is path-qualified section identifiers and 0019 is OCR scanned reprints, both landed after
#56 was written. The new record is 0020.

It states four things: the source class split; that commentary is never citable; that the
allowlist is a trust boundary; and that ADR 0016's receipt guarantee is unchanged. It amends
ADR 0001's legislation-only scope.

It must also settle the grounding question described in section 6 below. That is the design
decision in this issue, so it belongs in the decision record rather than in review.

**Files:** `docs/adr/0020-commentary-as-a-non-citable-source-class.md`

**Verified by:** the `plain-english` skill. No tests to run.

### Phase 2 — State, flag, reset. Nothing produces or consumes yet.

- `CommentaryNote` and the `commentary` channel on `AgentState` (`agent/state.py`).
- `commentary` as a `NotRequired` field on `QueryResult` and `QueryEvent`.
- Reset in `_start_turn` and `_retry_retrieve_node`, matching `reference_trace`.
- Flag into trace metadata and `flag_tags` (`agent/query_lifecycle.py:61-76`).

```python
class CommentaryNote(TypedDict):
    url: str
    title: str
    publisher: str        # the allowlist entry that served it
    published_date: str   # "" when the source gives none
    retrieved_at: str
    snippet: str
```

**Files:** `agent/state.py`, `agent/graph.py`, `agent/query_lifecycle.py`, `.env.example`,
`CONTRIBUTING.md` (the flag entry — CONTRIBUTING owns the detail), `CONTEXT.md` (the
**Commentary Note** domain definition).

**Verified by:**

```bash
python3 -m pytest -q
```

`tests/test_env_example.py` scans every `os.getenv` and `flag_enabled` call in the repo and
fails on a name missing from the template. It is what gates the flag reaching `.env.example`.

### Phase 3 — The tool. Depends on #119.

#119 is the shared allowlisted web search transport. It lands ahead of this plan because #60's
currency check needs it too and should not wait on the source class decision.

`search_commentary` in `agent/retrieval/tools.py`, returning a `Command` that writes
`commentary` and `tool_trace` and never `retrieved_chunks`. The allowlist is read from config
and passed to `agent/web_search.py`. The failure contract is at `agent/retrieval/tools.py:1-9`.

Two wrinkles in `agent/retrieval/agent.py`:

1. Two independent flags now give four tool-and-prompt combinations, so `@lru_cache(maxsize=2)`
   becomes 4 and `_build_retrieval_agent` takes both flags. Leaving it at 2 binds the wrong
   tool list under load, silently. The comment at
   `agent/retrieval/agent.py:112-114` explains why a shared variant is a bug; that reasoning now
   applies twice over.
2. Do **not** enumerate four state schemas to match. Declare `commentary` with its reducer on the
   base `RetrievalState` unconditionally and keep the two existing schema classes. An undeclared
   channel is what breaks; an unwritten one is harmless. `run_retrieval_agent` already adds keys
   to its result conditionally (`agent/retrieval/agent.py:222-230`), so flag-off output is
   unchanged either way.

**Files:** `agent/retrieval/tools.py`, `agent/retrieval/agent.py`, `tests/test_retrieval_tools.py`,
`tests/test_agentic_retriever.py`

**Verified by:**

```bash
python3 -m pytest -q tests/test_retrieval_tools.py tests/test_agentic_retriever.py
```

Plus the `tool_selection` eval, because the retrieval prompt changed and that eval asserts tool
order. `search_commentary`'s docstring is the schema sent to the model and drives tool
selection — behavior, not commentary, per the exception in CLAUDE.md. Write it at length; do
not trim it.

### Phase 4 — Gate tests. Tests only, no production code.

#56's Sequence is right that the risk sits here, and that it should land while the surface is
still invisible to a user. This phase turns every section 7 criterion into a test, except the
two that need a running model (Phase 5) and the UI one (Phase 7).

Two things the criteria do not tell you how to construct:

- The citation-presence test needs a control. A turn with commentary and no statute citation
  must produce the same violation and the same fallback as a turn with neither.
- Flag-off equivalence is asserted here for graph behaviour and SSE payloads only. Eval scores
  are Phase 5, because they need the model.

If a gate leaks, that is a finding. Stop and report it rather than patching it in this phase.

**Files:** `tests/test_commentary_gates.py` (new)

**Verified by:**

```bash
python3 -m pytest -q
```

### Phase 5 — Synthesiser and grounding. The risky one.

Prompt split in `agent/nodes/synthesiser.py`: cite sections for statements of law, mention
commentary for background, never let commentary carry a legal claim. Plus whatever Phase 1
decided for `grounding_check`.

The test that matters is not a unit test: it is a flag-on turn that uses commentary and
completes without reaching `MAX_RETRIES`. Phase 4's equivalence tests all pass with the flag off and will
not catch this.

**Files:** `agent/nodes/synthesiser.py`, `agent/nodes/grounding_check.py`,
`tests/test_grounding_check.py`, `tests/test_graph_reretrieve.py`

**Verified by:**

```bash
LANGSMITH_TRACING=false python3 -m pytest -q
```

Then the full eval suite: the section 7 guarantee, tested here for eval scores, plus no
degradation with the flag on.

### Phase 6 — SSE surface. No visible UI.

- `commentary` on the `response` event (`agent/query_lifecycle.py:252-257`) and on the sync
  `QueryResult` (`:156-166`), both conditional so an empty list is omitted.
- The SSE contract comment at `api/main.py:17-18`.
- Frontend decode in `queryTransport.ts`, then `useQuery`, `useResearchThreads`, `types.ts`.

The decoder reads fields one at a time and drops unknown ones
(`frontend/lib/queryTransport.ts:99-106`), so flag-off equivalence on the client is free.

**Files:** `agent/query_lifecycle.py`, `api/main.py`, `frontend/lib/queryTransport.ts`,
`frontend/lib/useQuery.ts`, `frontend/lib/useResearchThreads.ts`,
`frontend/components/locus-workspace/types.ts`, `README.md`, `CONTRIBUTING.md`

**Verified by:**

```bash
cd frontend && npm test
```

### Phase 7 — UI block. Last, and the least testable.

A commentary block in `Messages.tsx`, structurally separate from both `SOURCE MAP` and
`SOURCES USED`.

The requirement is that a practitioner who skims can tell the two apart without thinking about
it. No test asserts that. It needs a human eye before merge.

**Files:** `frontend/components/locus-workspace/Messages.tsx`, plus a new component test

**Verified by:**

```bash
cd frontend && npm test
```

## 6. Gotchas (do not skip)

**The grounding feedback loop.** This is the failure mode most likely to reach production, and
#56's acceptance criteria contain both halves of it. One criterion requires `grounding_check` to
label a claim supported only by commentary as `unsupported`. Scope requires the synthesiser to
mention commentary for background. Both at once ends every commentary turn in the fallback:

1. A background sentence is a legal claim with no cited source, so the judge labels it
   `unsupported` (`agent/nodes/grounding_check.py:186-195`).
2. That appends to `evidence_violations`, which routes to `retry_retrieve` rather than a
   re-draft (`agent/graph.py:99-106`).
3. Retries burn to `MAX_RETRIES`, and `delivered_response` returns `FINAL_FAILURE_RESPONSE`
   (`agent/query_policy.py:68-69`).

Phase 1 picks the fix: scope the judge to sentences carrying a citation marker, or confine
commentary prose to a block the judge skips. Phase 5 implements it and proves it with a flag-on
test.

**The lru_cache.** Four flag variants, a cache sized for two, and the failure is silent. See
Phase 3, wrinkle 1.

**Tool docstrings are behavior.** Not prose to trim. See Phase 3, verification.

**Every env var must reach `.env.example`.** See Phase 2, verification.

## 7. Acceptance criteria

Taken from #56, with the rename applied and the grounding rule added:

- With `WEB_COMMENTARY_ENABLED` unset, graph behaviour, SSE payloads, and eval scores are
  identical to today.
- A commentary note can never satisfy citation presence.
- `grounding_check` never labels a claim supported only by a commentary note as `supported`.
- A turn that uses commentary still finishes without reaching `MAX_RETRIES`.
- No commentary note ever reaches `retrieved_chunks`, and no `Citation` is ever built from one.
- A domain outside the allowlist is dropped, with a counter recorded.
- Search failures and timeouts return a `ToolMessage` the model can act on.
- The UI renders citations and commentary in separate blocks with distinct affordances.
- ADR 0020 records the source class split and its relation to ADR 0001 and ADR 0016.
- `README.md`, `CONTRIBUTING.md`, and `CONTEXT.md` carry the flag, the new event field, and the
  definition of a commentary note. `CONTRIBUTING.md` owns the flag and allowlist detail; the
  other two link to it.

## 8. Rollback

Set `WEB_COMMENTARY_ENABLED=off` and restart workers. The cached disabled agent variant exposes
only the tools it exposes today, the channel stays empty, and the SSE field is omitted. No
database change, no corpus change, no artifact to revert.

Code rollback, if needed, reverts phases in reverse order. Phases 1 and 2 are safe to leave in
place: an unwritten channel and a decision record change no behaviour.

## 9. Branch and PR breakdown

One PR per phase, each referencing #56. Branch off `main`, never commit to it.

| Phase | Branch | Depends on |
| --- | --- | --- |
| 0 | none — a comment on #56 | — |
| 1 | `docs/adr-0020-commentary-source-class` | Phase 0 |
| 2 | `feat/56-commentary-state-and-flag` | Phase 1 |
| 3 | `feat/56-search-commentary-tool` | Phase 2, #119 |
| 4 | `test/56-commentary-gates` | Phase 3 |
| 5 | `feat/56-synthesiser-commentary-split` | Phase 4 |
| 6 | `feat/56-commentary-sse-surface` | Phase 5 |
| 7 | `feat/56-commentary-ui-block` | Phase 6 |

Related: #56, #60, #119, ADR 0001, ADR 0011, ADR 0016.
