"""
Conversational node — handles non-legal turns (greetings, names, thanks, small
talk, meta questions) with a warm, human reply.

The router classifies unambiguously social/meta messages as `conversational`, and
the graph routes them straight here, bypassing retrieval and the supervisor. This
node mirrors the `_escalate_node` shape — it sets `final_response` and the turn
flows to `record_turn` — but generates varied text with a small, hot LLM instead
of returning a fixed string.

Contract:
  - Runs at temperature 0.7 so repeated greetings vary in wording.
  - Mirrors the user's language (EN / BM / mixed) via response_language.
  - Reads trimmed Conversation History so "what's my name?" recalls a name given
    earlier in the thread.
  - Fails CLOSED: any exception returns the static CONVERSATIONAL_FALLBACK_RESPONSE
    rather than surfacing a raw error.
  - Never invents statute text or legal facts; offers to look things up instead.
"""
import logging
import os

from dotenv import load_dotenv

from agent.llm_factory import make_llm, system_content
from agent.query_policy import CONVERSATIONAL_FALLBACK_RESPONSE, trim_history
from agent.state import AgentState

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = os.getenv("CONVERSATIONAL_MODEL", "gpt-4.1-mini")
_llm = make_llm(_MODEL, temperature=0.7)

_LANGUAGE_PERSONA = {
    "en": "Reply in English.",
    "bm": "Reply in Bahasa Malaysia.",
    "mixed": "Reply in a natural mix of Bahasa Malaysia and English, matching the user.",
}

_SYSTEM = """You are the friendly front desk of a Malaysian legal research assistant. \
This message is small talk, not a legal-research question.

Be warm, human, and composed — like a helpful colleague, not a form letter. Vary \
your wording; never open with the same fixed stem every time.

- If the user gives their name, acknowledge it naturally.
- Briefly orient them: you research Malaysian legislation and cite the sources, and \
invite a legal question when it feels natural.
- {language_persona}

Hard guardrails:
- Never invent statute text, section numbers, or legal facts from memory.
- If they ask for any legal content, offer to look it up rather than answering it here.
- Never give advice about a specific situation.

Keep it short — a sentence or two."""


def conversational_node(state: AgentState) -> dict:
    history = trim_history(state.get("history", []))
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    response_language = state.get("response_language", "en")

    system_prompt = _SYSTEM.format(
        language_persona=_LANGUAGE_PERSONA.get(response_language, _LANGUAGE_PERSONA["en"])
    )

    try:
        result = _llm.invoke([
            {"role": "system", "content": system_content(system_prompt, _MODEL)},
            {"role": "user", "content": f"Conversation history:\n{history_text or '(none)'}\n\nCurrent message:\n{state['query']}"},
        ])
        text = (result.content or "").strip()
        if not text:
            text = CONVERSATIONAL_FALLBACK_RESPONSE
    except Exception:
        # Fail closed: a warm static greeting, never a raw error.
        logger.warning("conversational_node failed; using static fallback", exc_info=True)
        text = CONVERSATIONAL_FALLBACK_RESPONSE

    return {"final_response": text, "draft_response": text}
