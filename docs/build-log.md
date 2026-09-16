# Build Log

Short notes on challenges and learnings while building this app.

---

<!-- Format: **YYYY-MM-DD** — what we hit or learned -->

**2026-09-09** — Built the BM-heavy eval set and recorded the bilingual baseline (issue #38). The dataset went from 11 BM/mixed cases to 40, split evenly between pure BM and code-switched. `language_register` stopped being a keyword check. Everything here is a measurement — nothing it exposed was fixed.

**The old assertion could not fail.** It looked for one BM function word in the response, matched as a substring, so "Under section 60A (seksyen 60A)..." passed as a BM answer. The substring matching also fired on English: "dan" is inside "abundant". The replacement (`evals/language_id.py`) splits a response on sentence boundaries, classifies each segment with `mesolitica/fasttext-language-detection-bahasa-en`, and weights by word count. Segment-level, not whole-text, for two reasons. The right answer to a code-switched query is bilingual: BM framing around English statute quotes. And fastText scores a whole document as whichever language has more words in it.

**Thresholds came from measured answers.** Every `bm` answer scored 1.00 and `mixed` answers ran 0.42 to 1.00, so the gates sit at 0.60 and 0.25. An English answer with a stray BM word scores 0.00 to 0.05.

**Applicability comes from the case's declared `language`, not from detecting the query.** Detection was tried first and is unreliable at query length in both directions: the classifier reads "Am I liable if I posted the comment online?" (an English escalation case) as 48% BM, and reads two of the code-switched cases as almost entirely English. Detecting would have pulled English cases into the gate and pushed real BM cases out of it. A declared label also means an English-only run never loads the model, so the CI smoke set is untouched.

**Baseline, against the current English-only corpus (49k chunks, 578 Acts).** Retrieval first, measured with the new `evals/retrieval_recall.py` (no LLM, one embedding call per case):

| subset | semantic @1 / @3 / @8 | retriever @1 / @3 / @8 |
|---|---|---|
| en (23 cases) | 78% / 96% / 100% | 83% / 91% / 96% |
| bm (17 cases) | 29% / 35% / 53% | 65% / 71% / 71% |
| mixed (19 cases) | 42% / 79% / 89% | 74% / 89% / 95% |

`semantic` is vector search alone; `retriever` mirrors `retriever_node`, which tries the exact section lookup first. The gap between the two columns for BM is the whole finding. Cross-lingual embedding is weak — BM recall@8 of 53% against 100% for English. The exact-lookup path already understands `seksyen`, and that is what rescues section-named BM queries. Topical BM, where no section is named, has nothing to fall back on.

**Every BM and mixed case fails end-to-end on the production path, and the cause is one English string.** Full-mode judge pass rate on the 40-case subset is 0/40, and the judge never ran on any of them: `language_register` failed 40/40 first. `supervisor_node` Rule 3 requires the literal "does not constitute legal advice" in the draft, but `synthesiser_node` appends `_DISCLAIMER_BM` for `bm` and `mixed`. Rule 3 fires, the graph retries, and the retry fails the same way. The turn ends in `FINAL_FAILURE_RESPONSE`, an English fail-closed message — correctly scored as an English answer to a BM question. Not fixed here; tracked in #46.

**With the supervisor out of the path, the picture is different.** Raw mode (router → retriever → synthesiser) on the same 40 cases:

| metric | result |
|---|---|
| `language_register` | 40 of 40 |
| `expected_section` | 29 of 36 cases that name one (81%) |
| judge | 30 of 33 cases that reached it (91%) |
| end-to-end `bm` | 12 of 20 |
| end-to-end `mixed` | 18 of 20 |

So BM synthesis is not the weak part. Every one of the 7 citation misses is BM-heavy (6 `bm`, 1 `mixed`). These are the numbers #41 (embedding bake-off) and #42 (reranking) should be compared against; the full-mode 0% only measures the disclaimer bug.

Two smaller things the measurement turned up. Exact lookup short-circuits semantic search, which costs one English case. `evidence-32a-1` asks about s.265A of the CPC, but the answer lives in Evidence Act s.32A. The lookup returns the named section and never retrieves the cross-referenced provision; vector search alone ranks it 1st. Separately, the deterministic escalation pre-check in `router_node` is English-only keywords, and whether the LLM router catches BM equivalents is unmeasured because there is no BM `block` case. Adding one is awkward: escalation replies in English by design, so a BM `block` case would fail the language gate even when the router behaves correctly.

**2026-07-11** — Gave retrieval real LLM tool-calling (ADR 0013). The retriever was the last fixed-dispatch node; replaced it with a `create_react_agent` that binds `search_statutes` + `lookup_section` and decides how to search, gated behind `AGENTIC_RETRIEVAL` and fail-open to the deterministic path. Also split the retry: an evidence-shaped violation now re-retrieves with feedback instead of re-drafting the same chunks. What shaped it:

- **The hard part was streaming, not the agent.** `create_react_agent` worked first try, but tool-call events wouldn't reach the UI. Root cause: a sub-agent invoked manually inside a node runs its **own** Pregel stream — its custom writes don't bubble to the parent graph, and forwarding the parent `config` gives the inner node a *real* writer that still writes to the inner stream. The fix that worked: stream the sub-agent (`stream_mode=["custom","values"]`) and re-emit each custom event through the parent writer, which the wrapper node obtains in its own context. Only graphs added as **nodes** auto-propagate; a manual `.invoke()` does not.
- **Tools return `Command(update=...)`, not text.** A custom `RetrievalState` with a `retrieved_chunks` channel (case-insensitive dedupe reducer) lets overlapping searches accumulate and the wrapper read rows back losslessly — no parsing chunk data out of `ToolMessage` strings.
- **Route the retry by violation *kind*, explicitly.** `citation_validator`/`grounding_check` tag evidence-shaped findings into a separate `evidence_violations` list (the producing node declares the kind) rather than sniffing violation strings at the router. Evidence gap → `retry_retrieve` (feedback-driven), policy/phrasing → re-draft. Budget stays `MAX_RETRIES=1`: one *smarter* retry.
- **The `tool_selection` eval only activates with the flag on.** The deterministic path emits no tool trace, so `expected_tool` is treated as absent when `AGENTIC_RETRIEVAL` is off — the default CI eval is untouched. Verified live: a topical query traces `['search_statutes','search_statutes']` (reformulated once), a named-section query traces `['lookup_section']`; tool_selection 2/2, judge 2/2.

Key learning: LangGraph stream propagation is the sharp edge of nesting agents. The mental model that fixed it — *manual invoke = separate stream; forward events yourself* — is the thing to remember for any sub-agent-inside-a-node design.

**2026-07-03** — Closed out the Semantic Memory lifecycle (ADR 0010, Phase 4): pruning + an eval. The write path only inserts, so the topic collection grows unbounded and `enable_inserts=True` can mint several profiles; `recall` hard-caps at 5 by similarity, so valuable-but-less-similar facts silently fall out of the top slots. The new `agent/memory/pruner.py` collapses duplicate profiles, consolidates near-duplicate topics, and evicts low-value topics by **importance + recency** — gated dark (`SEMANTIC_MEMORY_PRUNE`), off the hot path, fail-open, size-debounced. What shaped the design:

- **Importance = retrieval frequency, kept off the item.** `recall` records a hit per surfaced item in a side `(user_id, "semantic_meta")` namespace (written `index=False`) rather than on the item itself. Bumping the item would touch its `updated_at` and conflate "recalled" with "rewritten" — keeping stats separate lets recency stay the write-time and importance be the recall count.
- **Clustering rides the store, not a new embedding call.** Consolidation finds near-duplicates via the store's own `asearch(query=topic)`, so the pruner has no direct OpenAI dependency and no graph-build-on-import.
- **Not TTL.** Age is one weighted input against importance (`w_importance` > `w_recency`), so a stale-but-recalled fact outlives recent chatter — the exact failure mode ADR 0010 rejects.
- **`enable_deletes` stays off on the extractor.** Deletion lives in the pruner as a deliberate, separate pass, not a side effect of every write.

Key learning: the eval's deterministic `--dry` path needed reproducible vector scores. A bag-of-words stub index over `content.topic` only (structural tokens like `RecurringTopic` excluded from the embedded text) makes a reordered duplicate score 1.0 and an unrelated topic 0.0 — clustering is testable without an API call, and the same stub backs `tests/test_pruner.py`.

**2026-06-24** — Moved history trimming from turn-count to a **token budget** (`MAX_HISTORY_TOKENS`, ADR 0008). What changed:

- **Token budget, not turn count.** Drop whole turns oldest-first until the rest fits. Soft budget with a hard floor — the newest turn always survives.
- **One local `tiktoken` proxy** across all three providers. Trimming tolerates approximation, so determinism + zero network beat per-provider exactness.
- **Built `evals/history_budget.py`** (contextualize-only, ~$0.0005/run) to tune the budget against real behavior instead of guessing a number.

The eval earned its keep. At a 2000-token budget, a referent 4 statute-heavy turns back was evicted — and contextualize didn't just lose it, it silently **rebound "it" to the most recent topic** (defamation) and emitted a confidently-wrong standalone query. Raising the default to 4000 closed it.

Key learning: the observed-failure discipline cuts both ways. The same eval that justified token budgeting also showed the summary buffer (Stage 3) is *not* warranted yet — a one-line budget bump fixed the failure. Raise the budget before reaching for summarization.

**2026-06-23** — Fixed the `MAX_HISTORY_TURNS` misnomer (flagged 2026-06-13). The constant counted *messages*, not turns: `=6` with `history[-6:]` kept 3 turns, so "6 turns" was really 3, and an even message-slice silently relied on the append-only paired-history invariant to avoid starting on a dangling assistant. Reworked `trim_history` to slice in whole turns (`max_turns`, default 3 — preserves the real prior behavior) and to drop a leading orphan assistant defensively, so boundary safety no longer depends on how the list was built. Pure correctness fix, no token logic yet; token-budget trimming is the next step (it's why the misnomer mattered — turn/message counting is a poor proxy for the thing we actually bound, which is tokens).

**2026-06-20** — Shipped history-aware retrieval, closing the 2026-06-13 gap (retriever embedded the bare follow-up). A `contextualize` node now rewrites elliptical follow-ups into a self-contained **Standalone Query** for retrieval; the raw query is preserved in history and is what escalation/synthesis see. Prerequisite: strip the appended disclaimer at record-time so nodes read clean history. Key call (ADR 0007): escalation stays on the raw query — never re-checked on the Standalone Query, since it stitches prior context back in and would mass-false-escalate.

**2026-06-13** — Analyzed memory/context management. Current design is stateless: frontend resends full `history` per request, graph runs ephemeral state with no checkpointer. Strong points: horizontal scalability, bounded context (`MAX_HISTORY_TURNS=6`), Claude prompt caching. Biggest gaps: retriever ignores history (follow-ups embed the bare query), no persistence (React-only thread state), turn-count trimming ignores token size. Decided to add a LangGraph checkpointer for server-side conversation memory (the idiomatic pattern + fixes persistence). Wrote a full handoff plan for another agent: `docs/checkpointer-implementation-plan.md` — **pending implementation**. History-aware retrieval tracked separately.

**2026-05-16** — Diagnosed CI eval failure (issue #2) and published PRD. Surfaced a design conflict we hadn't noticed: synthesiser says "mixed query → default to English" but `language_register` assertion fires on any BM word in the query, so mixed queries *always* fail L1. Resolution: bilingual format for mixed queries (BM framing + English statute quotes inline + BM disclaimer). Also: prompt hardening alone wasn't enough — decided to add an explicit `response_language` field from the router rather than relying on the model to infer it from buried instruction #5. Doing both because they're complementary, not competing.

**2026-05-16** — BM/mixed language fixes (issue #2). Three compounding failures: `language_register` 0% (model drifts to English when all retrieved chunks are English), `expected_section` 50% (BM section/act keywords not parsed by retriever), judge 71% (below 80% CI gate). Fixed by: (1) adding `response_language` to router structured output so synthesiser gets an explicit signal instead of inferring from query text; (2) extending `_SECTION_RE` to match `seksyen/sek.` and adding BM act aliases to the alias table; (3) moving the language rule to position #1 in the synthesiser system prompt and adding a hardcoded BM disclaimer string. Key learning: vague rule #5 ("respond in the same language") was too weak — the model ignored it when all context was English. Explicit, first-position instruction with a `response_language` field from the router fixed it.

**2026-05-16** — Eval token cost is a real friction point. Running `--smoke` (15 cases) invokes Sonnet for router + synthesiser on every case — 30+ Sonnet calls per run. Haiku is only used for the judge. Need an `AGENT_MODEL` env var so local iteration can use Haiku; Sonnet reserved for CI. Also: results.json is written in one shot at the end, so Ctrl+C mid-run produces nothing usable. Incremental writes would help.

**2026-05-16** — Designed eval cost fixes (issue #3):
- Split into `ROUTER_MODEL` + `SYNTHESISER_MODEL` instead of single `AGENT_MODEL` — router is a simple classifier, synthesiser generates legal analysis; different quality requirements warrant separate knobs
- Added Anthropic prompt caching (1-hour TTL, inline `cache_control`) — router system prompt is fully static so case 1 warms the cache and all subsequent cases get 90% off; synthesiser caches up to 3 entries (one per language variant)
- L1 assertions are pure Python — zero LLM calls, unaffected by model choice
- L2 judge already on Haiku via existing `EVALS_JUDGE_MODEL` knob

Rejected options:
- Kimi — data residency concern (Chinese company, Malaysian legal tool)
- Response/semantic caching — would cache agent outputs and make evals blind to regressions
- `AnthropicPromptCachingMiddleware` — requires full `langchain` package which isn't installed

**2026-05-16** — Diagnosed agent over-refusing on allow-policy cases (judge 28.6%, all via FINAL_FAILURE_RESPONSE). Three compounding bugs found via node-by-node debug tracer (`evals/debug_case.py`):

1. **supervisor regex too narrow** — `section\s+\d+\s+of\s+.{5,60}act` requires "act" in the Act name; "Penal Code" and "Criminal Procedure Code" use "Code" so Rule 2 always fired, forcing a retry that would otherwise pass. Fixed: added `(?:act|code)` alternation.

2. **grounding_check too strict** — `partial` claims treated same as `unsupported`. On the forced retry (from bug 1), synthesiser rewrote the answer with interpretive glosses that grounding_check marked `partial`, producing FINAL_FAILURE_RESPONSE. Fixed: only flag `unsupported`.

3. **synthesiser drops citation_refs** — Sonnet correctly mentioned sections in prose but omitted them from the structured `citation_refs` field; citation_validator caught the mismatch and blocked every Evidence Act case. Fixed: added explicit rule 7 in system prompt ("include an entry for EVERY section you mention").

Key learning: Haiku cannot reliably populate structured output fields (`citation_refs: []` every time despite correct prose) — unsuitable for synthesiser. Safe for router (simple classifier). Built `evals/debug_case.py` as a repeatable single-case node tracer; faster and cheaper than running full evals to diagnose violations.

**2026-05-17** — Validated GPT-4.1 as production router + synthesiser (issue #4). Long path to get there:

1. **GPT-4.1-mini failed outright** — 0% BM language register, 20% `expected_section`, 50% judge. Not a model capability issue alone: the BM smoke cases were premature (v1 pilot corpus is English-only; BM retrieval degrades by design until BM corpus is ingested). Removed smoke tag from the 5 BM/mixed cases.

2. **Supervisor citation regex was broken for all non-Claude models** — pattern `section\s+\d+[A-Z]{0,2}\s+of\s+.{3,60}(?:act|code)` requires Act name immediately after the section number. Non-Claude models write `Section 90A(1) states that...` (subsection first, Act name earlier in the sentence). Every non-Claude response failed Rule 2, triggered retries, then hit FINAL_FAILURE_RESPONSE. GPT-4.1 went from 30% → 80% judge pass rate after extending the regex to also accept `section\s+\d+[A-Z]{0,2}\s*\([^)]+\)`. Key learning: the supervisor was silently calibrated to Claude's citation style — any future model trial would have hit the same wall.

3. **GPT-4.1-mini still failed after the regex fix** — 40% `expected_section`, 57% judge. Not a pipeline bug; the model genuinely cannot reliably identify the correct statute section on citation-heavy queries.

4. **GPT-4.1 passes at exactly 80%** — all L1 assertions 100%, judge 8/10. cheaper than Sonnet (not the 8× target), but the eval friction was about running freely, and at this price point it's acceptable. Provider-agnostic `agent/llm_factory.py` introduced: routes `claude-*` to ChatAnthropic, `gemini-*` to ChatGoogleGenerativeAI, else ChatOpenAI. Makes future model trials a one-line env var change.

Also tried: Gemini 2.5 Flash (would be ~15× cheaper) — hit free-tier 5 RPM cap on case 3. Needs billing enabled to run the eval. Deferred.

**2026-05-17** — Further eval cost investigation. Four things surfaced:

1. **Prompt caching still not firing** — both system prompts are ~266 tokens, well below Anthropic's 1024-token minimum. The `cache_control` blocks in router.py and synthesiser.py are silently no-ops.

2. **Batch API doesn't solve the real problem** — the Batch API (50% off) brings the run from $0.045 → ~$0.022. Not enough. Also, the sequential pipeline (router → retriever → synthesiser) means three separate batch submissions with sync retriever work in between — structurally more complex than the sync runner.

3. **Cost vs fidelity are in direct tension** — every cheaper-model option (Haiku, per-case routing) introduces false positive/negative risk because the eval tests a different model than production. Previous session already confirmed Haiku is unsuitable for synthesiser (drops `citation_refs`). The only real lever is making the production model cheaper.

4. **Decision: validate GPT-4.1-mini as production swap** — ~8× cheaper than Sonnet (~$0.006/run). Because eval and production would use the same model, fidelity is preserved. Published PRD (issue #4). Acceptance bar: judge pass rate ≥ 80%, `citation_existence` 100%, all 4 BM/mixed smoke cases pass. No Sonnet baseline run needed — thresholds are absolute, not relative.

**2026-07-05** — Semantic Memory extraction wasn't capturing answer-format preferences, so the write→recall→synthesise loop had no cleanly UI-observable effect. The one visible axis (response language) is deliberately guardrailed out (router sets language from the current query; synthesiser rule #1 overrides), leaving answer format/brevity as the only demonstrable signal — but `citation_style` came back `None` even for near-verbatim examples of the schema's own hint ("keep answers brief and concise").

Root cause was framing, not control flow: the field was named/described as **citation** style and the extractor instructions listed only "Citation / formatting style preferences", so gpt-4.1-mini didn't classify "give me bullets" / "be brief" as citation style, and the "when in doubt, do not store it" guard tipped it toward skipping. Fix (prompt/description only): widened the `citation_style` field description to cover response format/length/structure, made the extractor's formatting bullet explicit and exemplified, and added one line clarifying that a direct instruction about answer presentation IS a durable preference worth storing. Confidentiality block and the "when in doubt" guard left intact. Repro now populates `citation_style` across phrasings ("brief and concise", "use bullet points", "state the section number first") and recall surfaces it on a fresh thread. Kept the field name `citation_style` — recall renders it generically and a rename would ripple into stored data + tests.


**2026-09-14** — Ran the Nemotron-on-Nebius compatibility matrix for issue #59. The factory change works. The tier split documented alongside it does not, and the reason turned out to be the opposite of the first reading.

Nebius serves eight Nemotron variants; an API key exposes four of them serverless. Their ids are not their Hugging Face repo names — `nvidia/nemotron-3-super-120b-a12b` is lowercase, which the first draft of `CONTRIBUTING.md` guessed wrong.

Everything non-structured passes on every tier: plain completion, `.stream()`, `.ainvoke()`, and `bind_tools` — the retrieval agent picked `search_statutes` unprompted. An unknown model id returns a clean 404, so a typo fails loudly.

Structured output splits the models, and quantization predicts the split better than size does:

| Model | Quantization | `with_structured_output`, real router prompt, 5 queries |
|---|---|---|
| Nemotron-3.5-Lightning (30B) | BF16 | 5/5 |
| Nemotron-3-Ultra-550b-a55b | FP4 | 5/5 |
| NVIDIA-Nemotron-3-Nano-30B-A3B | FP8 | 4/5 |
| nemotron-3-super-120b-a12b | FP4 | 0/5 |

The first reading of this was that Nebius accepts `response_format: json_schema` and does not enforce it. That is wrong: Lightning and Ultra honour it, nested `_GroundingOutput` included. It is per-model. Super is simply broken on it — it returns 200 and hands back YAML (`standalone_query: "..."`), 0/5, every schema.

Nano's failure is different and intermittent: handed a json_schema it sometimes reasons past the 8192-token ceiling and raises `LengthFinishReasonError`, where the same prompt unstructured finishes in 114 tokens. `max_tokens=2048` does not bound it — the endpoint still reports 8192. Longer prompts trigger it more: the grounding check's ~2000-token prompt hit it on Lightning too, with `reasoning_tokens=8192`.

`method="function_calling"` is rejected outright with a 422 on every model: LangChain sends `parallel_tool_calls` and Nebius's body parser refuses the extra field. Plain `bind_tools` sends no such field, which is why tool binding works and function-calling structured output does not.

Smoke evals, all seven nodes on Lightning, judge on the usual Claude Haiku:

| Assertion | Result |
|---|---|
| Judge | 7/8 = 87.5% |
| citation_existence | 6/6 = 100% |
| expected_section | 3/5 = 60% |
| section_recall | 1/1 = 100% |
| uuid_leakage | 10/10 = 100% |
| ai_refusal | 8/8 = 100% |

Above the 80% judge gate. One case lost its grounding check to the token ceiling and failed open exactly as designed — the turn completed and the judge passed it, with the skip recorded in the log. That is the fail-open rule earning its place. It also means grounding verification is silently intermittent on this provider — a real degradation, not a clean pass.

That gate turned out not to be sufficient evidence. Run end to end through the API and the browser, a statute-lookup query on all-Lightning fell back to `FINAL_FAILURE_RESPONSE`. Retrieval was correct — Act 56 s.90A was the top hit, and the prose named the section. But `citation_refs` came back empty, so `citation_validator` blocked the answer. Three runs each on the same query: Ultra populated citations 3/3, Lightning 1/3, Nano 1/3 with two token runaways. This is the failure Haiku showed on 2026-05-16, and a judge pass rate cannot see it, because it averages over cases and the smoke set happened not to hit it.

So the worked example in `CONTRIBUTING.md` now splits the tiers — Lightning for router, contextualize, conversational and memory extraction; Ultra for synthesiser, grounding check and the retrieval agent. A live turn on that split produced a real answer with zero violations and a receipt-backed citation. The smoke table above was measured on all-Lightning and does not cover it.

Two things only the end-to-end run could find. One was the citation gap above. The second was a rendering bug in #61. The PROCESS panel's model rows reused a grid whose first column is 24px, sized for a two-digit step number. A node name overran it into the model id and rendered as overlapping text. Every `getByText` assertion passed, because jsdom computes no layout. Both were obvious within one turn of actually using the thing.

The error shaping added in #59 named the node and the model on every failure except `LengthFinishReasonError`, which openai raises from its own parser with no status code — the classifier missed it and it propagated raw. Added by class name, with `ContentFilterFinishReasonError` alongside.

**2026-09-16** — #93 (front matter and the table of contents as a division) turned into two real bugs found by measuring against the local corpus instead of trusting the first pattern that matched a few examples.

The design: find each Act's enacting formula (the fixed "BE IT ENACTED..." / "DIPERBUAT..." clause that opens the body) and treat everything before it as front matter, gated out of `_extract_chunks`'s section-matching loop entirely. First occurrence, first language-matched pattern, wins.

First bug: the Malay pattern. A first cut anchored on the bare word "diperbuat" (optionally preceded by "maka inilah"), mirroring how the English pattern anchors on "be it enacted". Sampling `data/pdfs/objects` — 481 real bm documents, all local, none of which I'd checked existed before writing the pattern — broke it immediately on Act 587 (Danaharta): its real clause is "MAKA, OLEH YANG DEMIKIAN, INILAH DIPERBUAT \nUNDANG-UNDANG oleh ...", which AGC splits across a line break, so a single-line bare-word match skipped 73 pages past it to a transitional-provision heading that happens to end "...akan \ndiperbuat" with nothing else on that line. First-occurrence-wins took the heading. `assigned_chars` for that one document fell from 117,556 to 11,238 — sections 1 through 68 read as front matter. Fix: require "diperbuat" to carry its collocate ("undang-undang" or "oleh parlimen malaysia"), and check each line joined with the one before it as well as alone, so the clause is still found on whichever side of the line break either half landed.

Second bug: even English, whose pattern was checked against an 80-document random sample before landing, had a case that sample missed. Act 136 (Contracts Act 1950, 91 pages) reprints, in an APPENDIX on page 87, the complete text of an amending Act — including that Act's own "BE IT ENACTED". Act 136's own clause doesn't match this pattern at all (a plain miss, same as the ~22% of Acts with no clause), so first-occurrence-wins landed on the appendix instead, and the entire real body read as front matter. Running the boundary-finder over the full local corpus (1,124 documents, both languages) rather than a sample found the shape of the problem precisely: of 859 documents with any match, the 99th percentile lands on page 21 and the deepest legitimate one is page 35 of 687 (Act 777, Companies Act — a big document with a table of contents to match), while Act 136's false one is page 87 of 91. Fix: a match past half the document (with a floor so a short document's first page isn't excluded by its own fraction) doesn't count — the same "leave it exactly as it stands today" fallback an undetectable clause already gets.

Net effect on the corpus, measured with `corpus shadow-extract` + `diff_chunk_sets` against the prior checked-in report: retention 92.52% → 92.27% (expected — a table-of-contents row that used to start a bogus chunk no longer can, see the `RECORDED_RETENTION_BASELINE` comment), unassigned share 3.69% → 1.49%, `toc_oracle` flagged chunks 133 → 90. 86 documents changed, every change a pure removal (0 added, 165 removed, 0 changed) — checked by size as well as count, since a removal count of 1 could still hide one large real chunk; it never did. The pattern across both bugs: a first cut that looks right against a handful of examples, and a specific, real, checkable-in-minutes corpus scan that finds the one document where it silently deletes most of an Act.

**2026-09-16** — #94 (a numbering scheme per division) rescued 15 of #72's 22-document cohort, and surfaced two more real bugs the same way #93's did: only visible once the extractor ran over the whole local corpus, not the fixtures or a sample.

The feature: a bare `<n>.` printed alone on its own line (title above, text below) is now a real section inside the body. The same shape is recognised inside a schedule's own paragraphs, plus `ARTICLE n` for a schedule that reprints an incorporated instrument's own scheme. Together they turn 15 of the cohort's documents from zero chunks to one chunk per real section.

First bug: the bare-line pattern needs #93's front-matter boundary to be safe, and doesn't check that it has one. Act 595 EN's real clause is a "WHEREAS ... provides:" recital, with no "BE IT ENACTED" anywhere in it. So `_enacting_formula_start` correctly returns `None`. With no boundary to gate it, its own table of contents — number first, title second, the AGC layout #72 already named as the discriminator — reads as body text. It then passes the bare-line gate exactly like a real split heading. Caught by re-running the extractor over the real corpus and diffing every document's character count against the prior report; none of the unit fixtures exercised a document with an undetectable formula and a same-shaped bare-line body. Fix: the bare-line pattern only fires when `enacting_start is not None`; without it, the document stays exactly as safe (and as unfixed) as it was before #94.

Second bug, found the same way: a schedule's own paragraph or article number can restart lower than one already used, and last-wins dedup silently prefers the later, wrong one. Act 4's Fifth Schedule (Employees' Social Security Act) restarts at "1." for its Part II, after Part I already reached "16." Both parts are now individually addressable for the first time, but both are keyed only by `(division, section_number)`. So Part II's "1" overwrote Part I's real "1," costing 30,475 characters on that one document alone. A second document, Act 595 BM, showed the same failure mode from the opposite direction. Its Second Schedule heading was pruned by `_division_boundaries`'s existing "longer than the body it follows" heuristic — correct for Act 593, but wrong here: Act 595 BM is a short 11-section operative Act with a 79-article reprinted Vienna Convention attached. Without that heading as a boundary, the convention's own "(1)...(2)..." subsection numbers — once per article — read as fresh body sections. They repeatedly restarted "1" against real sections 1 through 11, losing 51,014 characters on that document. Fix: track the highest token seen per division and refuse a bare-line or `ARTICLE n` match below it, folding the rejected content into whatever chunk is already open. The pre-#94 inline pattern (`SECTION_PATTERN`) is exempt from this: it always resets the watermark to its own value. That asymmetry is what lets a document like Act 318 BM self-correct the way it already did before #94. Its own undetected-formula table of contents matches inline on a handful of high numbers (`56.`, `57.`, ...) before the real body starts back at "1." The real inline "1." has always been trusted to supersede it — guarding the inline pattern too would have broken that existing self-correction instead of fixing anything.

Net effect, `corpus shadow-extract` against the full local corpus (1,099 ready documents) compared to the prior checked-in report: retention 92.27% → 92.35%, unnumbered blob chunks 1,967 → 1,858 (990K fewer undifferentiated characters), low-yield ready documents 66 → 38. `toc_oracle` flagged chunks also fell, 90 → 32, though that wasn't this issue's target — many of #97's second-cause chunks already had a real item number available once schedules got one, so they dropped too. The 7 members of the #72 cohort still not fully recovered are named, not silently short. Act 437 EN/BM turned out to be a genuine one-page "superseded by Act 865" stub with no body text to recognise at all — not what #72 originally assumed, since the source PDF has evidently been replaced since. Act 33/114/198/205/373 EN share Act 595's gap: a real enacting formula in a phrasing `ENACTING_FORMULA_PATTERNS` doesn't recognise yet.

The pattern across both bugs, again: a rule built exactly right for the case it was measured against can still be exactly wrong for a case shaped differently enough, and the corpus is the only place that difference shows up.

**2026-09-16** — #95 (path-qualified section identifiers) closes the #76 split. Adds a `path` column, additive like `division`. Moves `section_number` to body-only: a schedule item's number now lives only in its path (e.g. `sched.2/para.1`, `sched.1/art.20`), so it never collides with a body section that shares its number. `exact_section_lookup`'s `body_first` ordering hack is gone — dead now that `section_number` is body-only.

The real bug wasn't in the extractor. That code is unchanged by design: the ADR settles the identifier shape, not detection. The bug was in `agent/citation_keys.py`'s new `canonicalize_citation_key`. A first draft made `path` win over `section_number` whenever both were present, on the theory that path is the "real" identity. That is backwards. The LLM sees `section_number` in the synthesiser's bracketed chunk header, and echoes that exact string back in `citation_refs`. A body chunk always has both fields. So preferring path would key the chunk side on `"s.90A"` while the LLM kept echoing `"90A"` — every existing body citation would silently stop matching. The fix is section-number-first, path-as-fallback: a body chunk resolves through `section_number` exactly as before, and path is only consulted when `section_number` is empty. A caller with no separate path field (an LLM or judge echo) still resolves a path-shaped string through that same fallback: `canonicalize_section_number` cleanly rejects `"sched.2/para.1"`-shaped input, so this works. A second review pass in plan mode caught this before it shipped — not a test. The failure is a silent 100%-of-body-citations regression, and a unit test written under the same wrong assumption would not have caught it either.

Verified against two real local documents rather than trusting the design. Act 4 (Employees' Social Security Act) has ten schedules — the same restart shape #94's entry above measured. Act 512 (Geneva Conventions Act) has three schedules of `ARTICLE n`-numbered incorporated text, 369 non-body chunks between them. Every path came out unique on both, with no collisions. Lettered suffixes (`sched.3/para.1A`) resolved correctly, and so did multi-schedule ordinals (`sched.1` through `sched.10`, by appearance order, matching the printed labels). `pdf_chars`, `assigned_chars`, `classified_chars`, `unassigned_chars`, and every `unnumbered_chunks` entry came back byte-for-byte identical to the pre-#95 baseline (`EXTRACTOR_VERSION` 2.4.0) on both documents. Only `extraction_id`/`chunk_set_hash` changed. That's expected: this relabeling adds an identity field without touching any boundary decision. `EXTRACTOR_VERSION` 2.4.0 → 2.5.0; no activation, matching #93 and #94's precedent.

**2026-09-16** — Re-diagnosing #97's `toc_oracle.flagged` list (32 chunks) after #93/#94 found the checked-in `data/chunks/extract_report.json` was itself stale, and found a wrong claim in the process.

The report's last commit was a6154bc (#94, 10:44). #95 (2e5ecba, 12:33 the same day) landed after that and nobody re-ran the extractor to refresh it. Concrete proof, not just a timestamp argument: the tracked report has Act 26 EN's flagged THIRD SCHEDULE chunk at `"section_number": "23"`; re-running `_extract_chunks` against that same PDF right now gives that chunk `section_number=""` and `path="sched.3/para.23"` — exactly #95's move of `section_number` to body-only. A full corpus re-run (1,099 ready documents, ~18 minutes) confirmed the flagged *count* still holds at 32 and the per-chunk fields elsewhere are close but not identical (`unnumbered_chunk_count` 1,858 → 1,860, `chunk_size_distribution["1"]` 29,474 → 29,461) — small, real second-order shifts from #95's dedup key moving from `(division, section_number)` to `(division, path)`, not noise.

Splitting the 32 by division: 28 sit in `body`, 4 sit in a real schedule division. The previous comment on #97 had sampled 4 of the 32 and called the `body` ones "documents #101 already tracks." Checked all 28 properly this time (not a sample) — they trace to 13 documents, and none of the 13 is one of #101's own six (`595, 33, 114, 198, 205, 373`). Landing #101 as scoped would not have touched this list at all.

Reading the 13: 12 are pre-Merdeka colonial Ordinances with no enacting clause anywhere in the reprint (confirmed page-by-page for two, keyword-scanned for the rest) — AGC's "First enacted" commencement-metadata line and then straight into "ARRANGEMENT OF SECTIONS" / "SUSUNAN SEKSYEN", nothing clause-shaped between. `_enacting_formula_start` returning `None` for these is its own documented, correct behaviour, not a pattern gap — #101's fix (extend `ENACTING_FORMULA_PATTERNS`) has nothing to match here. Filed separately (#110) rather than folded into #101, since mixing "no clause exists" into #101's "real clause, wrong pattern" scope would have muddied both. The 13th, Act 747 EN, does have a real clause the pattern misses — "`NOW, THEREFORE, pursuant to Article 149 of the Federal Constitution IT IS ENACTED by the Parliament of Malaysia as follows:`" — neither EN pattern matches it, because "ENACTED" isn't the line's first word and the verb is "IT IS ENACTED" rather than "BE IT ENACTED". That one's a genuine 7th example for #101, not a new issue.

The remaining 4 (root cause 2, #97's own original second cause — a schedule's own internal arrangement-of-paragraphs list) are still fully live and still unaddressed by #93/#94/#95, same as when #97 was filed. Only one of the four had been checked directly before this pass.

**2026-09-16** — #101 (English enacting-formula pattern gap) turned out to be two findings, not one: a real phrasing gap for 3 of the 7 named documents, and a wrong shared-shape assumption for the other 4.

The issue's own Problem section assumed all six of #72's remaining low-yield cohort (Act 33, 114, 198, 205, 373, and 595 EN) shared one clause shape — a "WHEREAS ... provides:" recital like Act 595's own, just unrecognised. Reading each PDF's actual front matter directly, not inferred from title, found that wrong for 4 of the 6: Act 33, 114, 198, 205 EN carry no enacting clause of any kind — their AGC reprints go straight from the long-title bracket to "Short title", nothing WHEREAS- or ENACTED-shaped between. `_enacting_formula_start` returning `None` for these is correct and permanent, the same conclusion the #97 re-diagnosis above reached for a different cohort. Only Act 373 and 595 actually have a real, undetected clause, and Act 747 EN — added to the issue by comment, the same document the #97 re-diagnosis above surfaced — makes a third: "...IT IS ENACTED by the Parliament of Malaysia as follows" (595), "...IT IS HEREBY ENACTED by the Yang di-Pertuan Agong with the advice and consent of Parliament as follows" (373, a different actor), and "...pursuant to Article 149 of the Federal Constitution IT IS ENACTED by the Parliament of Malaysia as follows" (747, where a whole clause sits between "NOW, THEREFORE," and "IT IS ENACTED").

Fix: a third alternative, `IT\s+IS\s+(?:HEREBY\s+)?ENACTED\s+BY\b`, added to `ENACTING_FORMULA_PATTERNS["en"]`. Unlike the other two it carries no leading `^`, because Act 747's own physical line is "Constitution IT IS ENACTED by the Parliament of Malaysia as" — anchoring at the line start would miss it. It also doesn't try to match the actor, same reasoning as the existing "BE IT ENACTED" pattern: Act 373's actor is the Yang di-Pertuan Agong, not the Parliament of Malaysia. Checked against the old pattern's result on all 624 local English documents, not a sample, before touching the pattern and again after: zero documents' already-detected line changed, and 12 went from `None` to a real match — the 3 named above plus 9 more the pattern generalises to for free (Act 297, 622, 636, 641, 659, 660, 686, 712, 720), each verified by reading its matched page to confirm it really is the "WHEREAS ... NOW, THEREFORE, IT IS ENACTED ... as follows" opening and not a coincidence.

Net effect, `corpus shadow-extract` against the full local corpus (1,099 ready documents) compared to the prior checked-in report: retention unchanged at 0.9235 (assigned_chars +2,929, classified_chars +35,817, unassigned_chars -38,746 — most of the recovered text was already counted as classified front matter, not lost as unassigned body), low-yield ready documents 38 → 37. Act 373 EN is the only one of the twelve whose yield crossed the recorded threshold: 2 chunks/16.0% assigned → 11 chunks/69.4% assigned. Act 622 and 659 EN also gained a detected front-matter boundary but stay low-yield for an unrelated reason outside this issue's scope. `EXTRACTOR_VERSION` 2.5.0 → 2.6.0; no activation, matching #93/#94/#95's precedent.
