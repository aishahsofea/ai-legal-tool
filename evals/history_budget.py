"""Manual eval for the history token budget (MAX_HISTORY_TOKENS).

NOT a unit test — it's an instrument for *tuning* the budget. The deterministic
trim analysis is free; the resolution check makes one real `gpt-4.1-mini` call
per run (~$0.0005) and needs an OpenAI key.

It isolates the one property the budget affects: can `contextualize` still resolve
an elliptical follow-up after trimming? The transcript puts the referent
("Section 90A of the Evidence Act 1950") in the OLDEST turn, behind several
statute-heavy turns. A tight budget evicts that turn and the follow-up's "it"
becomes unresolvable; a generous budget keeps it. The crossover is what we tune.

Usage:
    python -m evals.history_budget                 # trim sweep + live resolution
    python -m evals.history_budget --dry           # trim sweep only (no API call)
    python -m evals.history_budget --budget 1500   # live check at a specific budget
"""
from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()

from agent.query_policy import MAX_HISTORY_TOKENS, count_tokens, trim_history

SEP = "-" * 68
REFERENT = "Section 90A"  # lives in the oldest turn; the follow-up depends on it

# A legal-padding clause used to inflate the intervening turns to a realistic,
# statute-heavy size so a 2k budget sits near the eviction crossover.
_PAD = (
    " The provision must be read together with its proviso and the relevant "
    "subsections, construed in light of the Act's purpose and prior judicial "
    "interpretation by the superior courts."
)


def _answer(core: str, pad_times: int) -> str:
    return core + _PAD * pad_times


# Oldest turn (index 0) introduces the referent; later turns are unrelated and
# large, so they consume the budget and push turn 0 out under a tight limit.
TRANSCRIPT: list[dict] = [
    {"role": "user", "content": "What does Section 90A of the Evidence Act 1950 cover?"},
    {"role": "assistant", "content": _answer(
        "Section 90A of the Evidence Act 1950 governs the admissibility of documents "
        "produced by a computer in the course of its ordinary use.", 13)},
    {"role": "user", "content": "And what about contracts made by minors?"},
    {"role": "assistant", "content": _answer(
        "Under the Contracts Act 1950, an agreement by a minor is void ab initio "
        "following Mohori Bibee, subject to the necessaries exception.", 18)},
    {"role": "user", "content": "How is criminal breach of trust defined?"},
    {"role": "assistant", "content": _answer(
        "Section 405 of the Penal Code defines criminal breach of trust where a person "
        "entrusted with property dishonestly misappropriates it.", 18)},
    {"role": "user", "content": "What are the remedies for defamation?"},
    {"role": "assistant", "content": _answer(
        "Defamation remedies under Malaysian law include damages and injunctions, with "
        "defences of justification, fair comment, and qualified privilege.", 18)},
]

# Elliptical follow-up: "it" can only mean Section 90A, which is in the oldest turn.
FOLLOWUP = "What are the conditions for it to be admissible?"


def _turns(history: list[dict]) -> list[list[dict]]:
    start = 0 if history[0]["role"] == "user" else 1
    return [history[i:i + 2] for i in range(start, len(history), 2)]


def _referent_survives(kept: list[dict]) -> bool:
    return any(REFERENT in m["content"] for m in kept)


def print_trim_sweep(budgets: list[int]) -> None:
    total = sum(count_tokens(m["content"]) for m in TRANSCRIPT)
    print(SEP)
    print(f"TRANSCRIPT: {len(_turns(TRANSCRIPT))} turns, {total} tokens total")
    print(f"REFERENT  : {REFERENT!r} is in the OLDEST turn")
    print(SEP)
    print(f"{'budget':>8} | {'kept tokens':>11} | {'turns kept':>10} | referent survives?")
    print("-" * 56)
    for b in budgets:
        kept = trim_history(TRANSCRIPT, max_tokens=b)
        kept_tokens = sum(count_tokens(m["content"]) for m in kept)
        n_turns = len(_turns(kept)) if kept else 0
        survives = "YES" if _referent_survives(kept) else "no  <-- follow-up unresolvable"
        print(f"{b:>8} | {kept_tokens:>11} | {n_turns:>10} | {survives}")
    print()


def run_live(budget: int) -> None:
    # Import here so --dry never imports the LLM client.
    import agent.nodes.contextualize as ctx

    kept = trim_history(TRANSCRIPT, max_tokens=budget)
    state = {"query": FOLLOWUP, "history": TRANSCRIPT}

    print(SEP)
    print(f"LIVE RESOLUTION  (budget={budget}, MAX_HISTORY_TOKENS default={MAX_HISTORY_TOKENS})")
    print(f"  follow-up      : {FOLLOWUP!r}")
    print(f"  referent kept? : {'YES' if _referent_survives(kept) else 'NO (evicted)'}")
    print("  calling contextualize (gpt-4.1-mini, ~$0.0005)...")

    # contextualize_node calls trim_history with its default budget (bound at
    # definition time), so to exercise a chosen budget we patch the name the
    # node resolves rather than mutating the constant.
    original = ctx.trim_history
    ctx.trim_history = lambda history, max_tokens=budget: original(history, max_tokens=max_tokens)
    try:
        result = ctx.contextualize_node(state)
    finally:
        ctx.trim_history = original

    standalone = result.get("standalone_query", "")
    resolved = REFERENT.lower() in standalone.lower() or "evidence act" in standalone.lower()
    print(f"  standalone_query: {standalone!r}")
    print(f"  RESOLVED?       : {'YES — referent carried forward' if resolved else 'NO — referent lost'}")
    print(SEP)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune the history token budget.")
    parser.add_argument("--dry", action="store_true", help="trim sweep only, no API call")
    parser.add_argument("--budget", type=int, default=MAX_HISTORY_TOKENS,
                        help="token budget for the live resolution check")
    args = parser.parse_args()

    print_trim_sweep([500, 1000, 1500, 2000, 3000, 4000])
    if not args.dry:
        run_live(args.budget)


if __name__ == "__main__":
    main()
