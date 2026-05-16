# Build Log

Short notes on challenges and learnings while building this app.

---

<!-- Format: **YYYY-MM-DD** — what we hit or learned -->

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

