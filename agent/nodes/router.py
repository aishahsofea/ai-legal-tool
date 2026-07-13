"""
Router node — classifies the query and detects escalation triggers.

Escalation is checked with keyword matching before any LLM call.
Classification uses structured output for the three non-escalation types.
"""
import os
import re
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel

from agent.llm_factory import make_llm, system_content
from agent.query_policy import trim_history
from agent.state import AgentState

load_dotenv()

_ESCALATION_PATTERNS = re.compile(
    r'\bmy client\b|\bam i liable\b|\bi have been charged\b|\bi was charged\b'
    r'|\bmy case\b|\brepresent me\b|\blegal advice\b',
    re.IGNORECASE,
)

_MODEL = os.getenv("ROUTER_MODEL", "gpt-4.1")
_llm = make_llm(_MODEL)


class _RouterOutput(BaseModel):
    query_type: Literal["statute_lookup", "topical", "provision_extraction", "conversational"]
    response_language: Literal["en", "bm", "mixed"]
    reasoning: str


_structured_llm = _llm.with_structured_output(_RouterOutput)

_SYSTEM = """You classify legal research queries from Malaysian law practitioners.

Set query_type to one of:
- statute_lookup: the user wants the text of a specific section or provision
  (e.g. "what does Section 114 of the Evidence Act say?")
- topical: the user wants to find which Acts or sections govern a topic
  (e.g. "which laws cover data privacy for employers in Malaysia?")
- provision_extraction: the user wants all provisions of a specific kind within one Act
  (e.g. "list all penalty provisions in the PDPA")
- conversational: the message carries no legal-research substance — greetings,
  self-introductions or names, thanks, small talk, or meta questions about the
  assistant itself (e.g. "hi", "my name is Shameel", "thanks!", "what can you do?",
  "how does this work?")

IMPORTANT tie-break: only use conversational when the message is UNAMBIGUOUSLY
social or meta. When in doubt — if the message has any legal substance at all —
classify it as one of the three legal types, not conversational.

Set response_language based on the dominant language of the current query:
- "en": query is primarily in English
- "bm": query is primarily in Bahasa Malaysia (e.g. contains "seksyen", "akta", "tolong semak", "bagaimana")
- "mixed": query meaningfully mixes both languages (e.g. "tolong check seksyen 34 Penal Code")

Reply with the most appropriate type, the response language, and a brief one-sentence reasoning."""


def _escalation_shortcut(state: AgentState) -> dict | None:
    # Escalation triggers are intentionally checked only against the current user
    # query. Assistant history contains the required legal-advice disclaimer, and
    # checking the combined transcript would make every follow-up escalate.
    if _ESCALATION_PATTERNS.search(state["query"]):
        return {"query_type": "escalate", "response_language": "en"}
    return None


def _build_messages(state: AgentState) -> list[dict]:
    history = trim_history(state.get("history", []))
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)
    return [
        {"role": "system", "content": system_content(_SYSTEM, _MODEL)},
        {"role": "user", "content": f"Conversation history:\n{history_text or '(none)'}\n\nCurrent query:\n{state['query']}"},
    ]


def _result(result: _RouterOutput) -> dict:
    return {"query_type": result.query_type, "response_language": result.response_language}


def router_node(state: AgentState) -> dict:
    if (short := _escalation_shortcut(state)) is not None:
        return short
    result: _RouterOutput = _structured_llm.invoke(_build_messages(state))
    return _result(result)


async def arouter_node(state: AgentState) -> dict:
    if (short := _escalation_shortcut(state)) is not None:
        return short
    result: _RouterOutput = await _structured_llm.ainvoke(_build_messages(state))
    return _result(result)
