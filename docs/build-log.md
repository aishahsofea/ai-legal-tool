# Build Log

Short notes on challenges and learnings while building this app.

---

<!-- Format: **YYYY-MM-DD** — what we hit or learned -->

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

