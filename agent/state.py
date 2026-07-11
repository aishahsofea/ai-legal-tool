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
    type: Literal["status", "tool_call", "response", "error", "done"]
    message: str
    name: str        # tool_call: which retrieval tool fired
    summary: str     # tool_call: human-readable description of the call
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
    retrieval_feedback: str  # feedback fed to the agentic retriever on a re-retrieval pass
    final_response: str
    retry_count: int
