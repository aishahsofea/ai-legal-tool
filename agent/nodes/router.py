"""
Router node — classifies the query and detects escalation triggers.

Escalation is checked with keyword matching before any LLM call.
Classification uses Claude structured output for the three non-escalation types.
"""
import os
import re
from typing import Literal

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from agent.state import AgentState

load_dotenv()

_ESCALATION_PATTERNS = re.compile(
    r'\bmy client\b|\bam i liable\b|\bi have been charged\b|\bi was charged\b'
    r'|\bmy case\b|\brepresent me\b|\blegal advice\b',
    re.IGNORECASE,
)

_llm = ChatAnthropic(model=os.getenv("ROUTER_MODEL", "claude-sonnet-4-6"), temperature=0)


class _RouterOutput(BaseModel):
    query_type: Literal["statute_lookup", "topical", "provision_extraction"]
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

Set response_language based on the dominant language of the current query:
- "en": query is primarily in English
- "bm": query is primarily in Bahasa Malaysia (e.g. contains "seksyen", "akta", "tolong semak", "bagaimana")
- "mixed": query meaningfully mixes both languages (e.g. "tolong check seksyen 34 Penal Code")

Reply with the most appropriate type, the response language, and a brief one-sentence reasoning."""


def router_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)

    # Escalation triggers are intentionally checked only against the current user
    # query. Assistant history contains the required legal-advice disclaimer, and
    # checking the combined transcript would make every follow-up escalate.
    if _ESCALATION_PATTERNS.search(query):
        return {"query_type": "escalate", "response_language": "en"}

    result: _RouterOutput = _structured_llm.invoke([
        {"role": "system", "content": [{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": f"Conversation history:\n{history_text or '(none)'}\n\nCurrent query:\n{query}"},
    ])
    return {"query_type": result.query_type, "response_language": result.response_language}
