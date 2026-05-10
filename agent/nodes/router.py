"""
Router node — classifies the query and detects escalation triggers.

Escalation is checked with keyword matching before any LLM call.
Classification uses Claude structured output for the three non-escalation types.
"""
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

_llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


class _RouterOutput(BaseModel):
    query_type: Literal["statute_lookup", "topical", "provision_extraction"]
    reasoning: str


_structured_llm = _llm.with_structured_output(_RouterOutput)

_SYSTEM = """You classify legal research queries from Malaysian law practitioners into one of three types:

- statute_lookup: the user wants the text of a specific section or provision
  (e.g. "what does Section 114 of the Evidence Act say?")
- topical: the user wants to find which Acts or sections govern a topic
  (e.g. "which laws cover data privacy for employers in Malaysia?")
- provision_extraction: the user wants all provisions of a specific kind within one Act
  (e.g. "list all penalty provisions in the PDPA")

Reply with the most appropriate type and a brief one-sentence reasoning."""


def router_node(state: AgentState) -> dict:
    query = state["query"]
    history = state.get("history", [])
    history_text = "\n".join(f"{turn['role']}: {turn['content']}" for turn in history)

    # Escalation triggers are intentionally checked only against the current user
    # query. Assistant history contains the required legal-advice disclaimer, and
    # checking the combined transcript would make every follow-up escalate.
    if _ESCALATION_PATTERNS.search(query):
        return {"query_type": "escalate"}

    result: _RouterOutput = _structured_llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Conversation history:\n{history_text or '(none)'}\n\nCurrent query:\n{query}"},
    ])
    return {"query_type": result.query_type}
