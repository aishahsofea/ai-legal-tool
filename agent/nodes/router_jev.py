"""Jev first pass for the router (#212). Off unless ROUTER_JEV_ENABLED is set.

`jev_route` raises JevError on any failure; the caller falls back to the LLM router.
"""
import os
from collections.abc import Callable
from contextvars import ContextVar

from agent import jev_client
from agent.jev_client import JevError
from agent.query_policy import trim_history
from agent.state import AgentState

# Shorter than the grounding 5s default: the router runs on every query, and Jev
# measured ~0.3s median, so a slow call is an outage and the LLM path is the better bet.
_TIMEOUT_S = 2.0

_QUERY_TYPES = ("statute_lookup", "topical", "provision_extraction", "conversational", "clarify")
_LANGUAGES = ("en", "bm", "mixed")

# Wording is the one measured in evals/routing_language.py (#212 Phase 3). The `bm` and `mixed`
# criteria were reworded against the dataset, so rewording them again invalidates that result.
QUESTIONS = {
    "query_type": {
        "type": "choice",
        "instructions": (
            "You classify legal research queries from Malaysian law practitioners. "
            "Tie-break: use conversational only when the message is unambiguously social or meta. "
            "Use clarify only when the history does not already supply the missing detail."
        ),
        "criteria": {
            "statute_lookup": "the user wants the text of a specific section or provision.",
            "topical": "the user wants to find which Acts or sections govern a topic.",
            "provision_extraction": "the user wants all provisions of a specific kind within one Act.",
            "conversational": "no legal-research substance: greetings, names, thanks, small talk, or questions about the assistant.",
            "clarify": "legal-research intent, but a detail is missing without which retrieval cannot proceed, such as a section number with no Act named.",
        },
    },
    "response_language": {
        "type": "choice",
        "instructions": "Judge the dominant language of the current query, not the history.",
        "criteria": {
            "en": "the query is primarily in English.",
            "bm": (
                "every word is Bahasa Malaysia (e.g. \"seksyen\", \"akta\", \"tolong semak\", \"bagaimana\"). "
                "English appears only inside a proper name such as an Act's title. A single English common word "
                "(\"section\", \"penalty\", \"employee\", \"list\", \"offence\") makes it mixed, not bm."
            ),
            "mixed": (
                "BM and English are both used in the query. Either BM grammar words (\"boleh\", \"apa\", \"dalam\", "
                "\"punya\", \"tak\", \"kat\", \"ke\", \"cakap\", \"dia\") around English common words that are not "
                "part of a name (\"Section 34\", \"offence\", \"penalty\", \"employee\", \"list\", \"personal data\"), "
                "or English grammar around BM words (\"which Act cover this kat workplace\"). "
                "An Act's English title inside a BM sentence does not count; an English common word does."
            ),
        },
    },
}


# Set only by evals/run_routing.py. Graph state stays unchanged, so the path is reported
# here instead of as a router output key: "jev", "llm" or "fallback" (Jev failed, LLM answered).
route_path_observer: ContextVar[Callable[[str], None] | None] = ContextVar(
    "router_route_path_observer", default=None
)


def report_path(path: str) -> None:
    observer = route_path_observer.get()
    if observer is not None:
        observer(path)


def model_name() -> str:
    return (os.getenv("JEV_MODEL") or "").strip()


def enabled() -> bool:
    return (
        (os.getenv("ROUTER_JEV_ENABLED") or "").strip().lower() in {"1", "true", "on", "yes"}
        and bool(os.getenv("TYPESAFE_API_KEY"))
        and bool(model_name())
    )


def _state_text(state: AgentState) -> str:
    # Same layout as the LLM router's user message, so both see the same context.
    history = trim_history(state.get("history", []))
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    return f"Conversation history:\n{history_text or '(none)'}\n\nCurrent query:\n{state['query']}"


def _choice(answers: dict, name: str, allowed: tuple[str, ...]) -> tuple[str, dict]:
    try:
        answer = answers[name]
        choice = answer["choice"]
    except (KeyError, TypeError) as exc:
        raise JevError(f"Jev answers missing `{name}`: {exc!r}") from exc
    if choice not in allowed:
        raise JevError(f"Jev returned an unknown `{name}`: {choice!r}")
    return choice, answer


def jev_route(state: AgentState) -> dict | None:
    """None when disabled. `query_type_probability` is for logging only; the caller must drop it."""
    if not enabled():
        return None
    answers = jev_client.classify(_state_text(state), QUESTIONS, timeout=_TIMEOUT_S)
    query_type, type_answer = _choice(answers, "query_type", _QUERY_TYPES)
    language, _ = _choice(answers, "response_language", _LANGUAGES)
    try:
        probability = float(type_answer["probabilities"][query_type])
    except (KeyError, TypeError, ValueError) as exc:
        raise JevError(f"Jev response had no usable `query_type` probability: {exc!r}") from exc
    if not 0.0 <= probability <= 1.0:
        raise JevError(f"Jev returned an out-of-range probability: {probability}")
    return {"query_type": query_type, "response_language": language, "query_type_probability": probability}
