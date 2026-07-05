from operator import add
from typing import Annotated, Literal, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class Citation(TypedDict):
    act_number: str
    act_title: str
    section_number: str
    pdf_url: str
    page_number: int | None


class QueryResult(TypedDict):
    query_type: str
    response: str
    citations: list[Citation]
    violations: list[str]


class QueryEvent(TypedDict, total=False):
    type: Literal["status", "response", "error", "done"]
    message: str
    content: str
    citations: list[Citation]
    violations: list[str]


class AgentState(TypedDict):
    query: str
    standalone_query: str    # history-resolved query for retrieval; "" = use raw query
    history: Annotated[list[Message], add]   # accumulate across turns
    query_type: str          # "statute_lookup" | "topical" | "provision_extraction" | "escalate"
    response_language: str   # "en" | "bm" | "mixed"
    retrieved_chunks: list[dict]
    draft_response: str
    citations: list[Citation]
    violations: list[str]    # supervisor findings; empty = pass
    recalled_memory: str     # Semantic Memory recalled for the synthesiser
    final_response: str
    retry_count: int
