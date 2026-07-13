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
    tool_trace: list[str]    # retrieval tools the agent called (agentic retrieval)


class QueryEvent(TypedDict, total=False):
    type: Literal["status", "tool_call", "response", "interrupt", "error", "done"]
    message: str
    name: str        # tool_call: which retrieval tool fired
    summary: str     # tool_call: human-readable description of the call
    content: str
    citations: list[Citation]
    violations: list[str]
    question: str        # interrupt: the clarifying question to put to the user
    interrupt_id: str    # interrupt: LangGraph interrupt id, echoed back on resume


class AgentState(TypedDict):
    query: str
    standalone_query: str    # history-resolved query for retrieval; "" = use raw query
    history: Annotated[list[Message], add]   # accumulate across turns
    query_type: str          # "statute_lookup" | "topical" | "provision_extraction" | "conversational" | "clarify" | "escalate"
    clarifying_question: str # set when query_type == "clarify"; drives the HITL interrupt (ADR 0015)
    clarified: bool          # True once this turn has asked one clarifying question — blocks a re-clarify loop
    response_language: str   # "en" | "bm" | "mixed"
    retrieved_chunks: list[dict]
    draft_response: str
    citations: list[Citation]
    violations: list[str]    # all findings (evidence + policy); empty = pass
    evidence_violations: list[str]  # subset from citation/grounding checks; drives re-retrieval routing
    recalled_memory: str     # Semantic Memory recalled for the synthesiser
    retrieval_feedback: str  # feedback fed to the agentic retriever on a re-retrieval pass
    tool_trace: list[str]    # retrieval tool names the agent called this turn
    final_response: str
    retry_count: int
