# Token-budget, turn-unit history trimming

Conversation history is trimmed before it reaches an LLM by a **token budget** (`MAX_HISTORY_TOKENS`, default 4000, env-overridable), not by a turn or message count. `trim_history` drops whole **turns** (user+assistant pairs) oldest-first until the remainder fits, and slicing in whole turns means a slice can never begin on a dangling assistant reply. The budget is a **soft target with a hard floor**: the most recent turn always survives even if it alone exceeds the budget, because a follow-up needs its immediate predecessor to resolve. Token size is measured with a **single local tokenizer** (`tiktoken` `o200k_base`) used as a proxy across all three providers (OpenAI, Anthropic, Gemini).

The thing we actually want to bound is prompt cost, latency, and distraction — all measured in tokens — so a turn/message count was only ever a proxy for it. The predecessor constant `MAX_HISTORY_TURNS = 6` was a double misnomer: it counted messages, so it kept 3 turns, not 6, and the even slice relied on an unguarded paired-append invariant to avoid a dangling assistant.

## Considered Options

- **Message- or turn-count trimming.** Rejected. Counting is a poor proxy for the real constraint: a statute-heavy legal turn can be 1–2k tokens while a "yes" is 5, so a fixed count makes prompt size — and cost — wildly variable. `evals/history_budget.py` quantified this: 4 statute-heavy turns spanned ~2,400 tokens, with single turns near 600.
- **Exact per-provider token counting** (tiktoken for OpenAI + Anthropic's `count_tokens` API for Claude). Rejected. Trimming tolerates approximation; exactness buys precision we never spend and adds a network round-trip plus coupling between the trimmer and whichever node calls it. A single local proxy tokenizer is deterministic and zero-network.
- **Per-node token budgets** (router vs contextualize vs synthesiser). Deferred. One shared budget keeps a single policy function; `trim_history(history, max_tokens=…)` is parameterised so a per-node split is a one-line change if an eval ever shows a node-specific need.
- **Summary buffer / message eviction for long conversations.** Deferred and gated. The gate is a *reproduced* eval failure where a referent is evicted even at a generous budget — not "conversations feel long." When built, it must be **additive**: a derived `history_summary` projected from history, with raw history kept append-only and immutable. Evicting messages to save tokens is rejected outright for this domain — the transcript is a legal **audit artifact** and must never be silently destroyed.

## Consequences

- The budget is a **cost/distraction knob, not an overflow guard** — gpt-4.1's window is ~1M tokens, so history never threatens it. Tune the budget against `evals/history_budget.py`, which exercises whether `contextualize` still resolves an elliptical follow-up after trimming.
- **Raise the budget before building a summary buffer.** The eval showed a 2000-token budget silently evicting a referent 4 turns back, causing `contextualize` to misresolve "it" to the most recent topic; raising to 4000 closed it. Budget tuning is the cheap first lever; the summary buffer (Stage 3) earns its complexity only when a generous budget still evicts referents.
- Raw `history` stays append-only (`Annotated[list[Message], add]`); trimming is a read-time projection that never mutates stored state. This preserves the audit trail and keeps the future summary buffer additive.
- `tiktoken` is a new runtime dependency.
