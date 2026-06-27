"""Shared query lifecycle policy constants."""
import os

import tiktoken

from agent.state import Message

# History token budget. History is re-sent on every turn, so a bigger budget
# costs more tokens (and latency) per turn, and past a point hurts answer quality
# as stale turns distract the model. The budget caps both.
#
# 4000 holds ~4+ statute-heavy legal turns. Tuned via evals/history_budget.py,
# which showed 2000 was too tight: it evicted a referent 4 turns back and made
# contextualize misresolve the follow-up.
MAX_HISTORY_TOKENS = int(os.getenv("MAX_HISTORY_TOKENS", "4000"))
MAX_RETRIES = 1
FINAL_FAILURE_RESPONSE = (
    "I wasn't able to put together a properly cited answer for that one. "
    "Could you try rephrasing the research question? If it concerns a specific "
    "situation, a qualified Malaysian lawyer is the right person to help."
)

# Static warm reply used when the conversational node's LLM call fails. Kept here
# beside the other canned responses so all user-facing fallback text lives in one
# place. Plain greeting only — no statute text, no disclaimer.
CONVERSATIONAL_FALLBACK_RESPONSE = (
    "Hi! I'm a research assistant for Malaysian legislation — ask me about an Act, "
    "a section, or a legal topic and I'll look it up and cite the sources. "
    "What would you like to explore?"
)

# Disclaimer suffixes appended by the synthesiser. Kept here as the single source
# of truth so strip_disclaimer removes exactly what was appended (no fuzzy matching).
_DISCLAIMER_EN = (
    "\n\n---\n"
    "*This information is for legal research only and does not constitute legal advice. "
    "Please consult a qualified Malaysian lawyer for advice on your specific situation.*"
)
_DISCLAIMER_BM = (
    "\n\n---\n"
    "*Maklumat ini adalah untuk tujuan penyelidikan undang-undang sahaja dan tidak merupakan "
    "nasihat undang-undang. Sila rujuk peguam Malaysia yang berkelayakan untuk nasihat berhubung "
    "situasi khusus anda.*"
)


def strip_disclaimer(text: str) -> str:
    """Remove the appended disclaimer suffix from an assistant response.

    Stored history should be disclaimer-free so later nodes (router, synthesiser,
    contextualize) don't re-read repeated boilerplate. We strip the exact suffix
    the synthesiser appended; text without a trailing disclaimer (escalation,
    fail-closed) is returned unchanged.
    """
    for disclaimer in (_DISCLAIMER_EN, _DISCLAIMER_BM):
        if text.endswith(disclaimer):
            return text[: -len(disclaimer)]
    return text


def delivered_response(state) -> str:
    """The response the user actually receives: the safe fallback when violations
    remain, otherwise the final draft. Single source of truth shared by the graph
    (history recording) and the query lifecycle (user-facing return).

    Does NOT strip the disclaimer — that stays a history-only concern.
    """
    if state.get("violations"):
        return FINAL_FAILURE_RESPONSE
    return state.get("final_response") or state.get("draft_response") or ""


# A single local tokenizer used as a size *proxy* across all providers (OpenAI,
# Anthropic, Gemini). Trimming tolerates approximation; we choose determinism and
# zero network over per-provider exactness. Lazily initialised so importing this
# module (done widely) doesn't load the BPE table unless trimming actually runs.
_ENCODER = None


def _encoder():
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("o200k_base")
    return _ENCODER


def count_tokens(text: str) -> int:
    """Approximate token size of a string, via the shared proxy tokenizer."""
    return len(_encoder().encode(text))


def trim_history(history: list[Message] | None, max_tokens: int = MAX_HISTORY_TOKENS) -> list[Message]:
    """Keep the most recent turns that fit a token budget before sending to an LLM.

    The checkpoint stores all turns forever, so nodes must trim at read-time to
    bound prompt cost. Applied inside the router, contextualize, and synthesiser nodes.

    Trims by token budget, dropping whole *turns* (user+assistant pairs) oldest-first.
    Slicing in whole turns means a slice can never begin on a dangling assistant reply.
    The budget is a soft target with a hard floor: the most recent turn always
    survives, even if it alone exceeds the budget (a follow-up needs its referent).
    """
    if not history:
        return []
    # Group into turns, defensively skipping a leading orphan assistant so a
    # malformed history can't produce a turn that starts on a reply.
    start = 0 if history[0]["role"] == "user" else 1
    turns = [history[i:i + 2] for i in range(start, len(history), 2)]

    kept: list[list[Message]] = []
    total = 0
    for turn in reversed(turns):
        turn_tokens = sum(count_tokens(m["content"]) for m in turn)
        if kept and total + turn_tokens > max_tokens:
            break
        kept.insert(0, turn)
        total += turn_tokens
    return [message for turn in kept for message in turn]
