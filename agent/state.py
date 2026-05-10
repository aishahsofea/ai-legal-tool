from typing import TypedDict


class Citation(TypedDict):
    act_number: str
    act_title: str
    section_number: str
    pdf_url: str
    page_number: int | None


class AgentState(TypedDict):
    query: str
    query_type: str          # "statute_lookup" | "topical" | "provision_extraction" | "escalate"
    retrieved_chunks: list[dict]
    draft_response: str
    citations: list[Citation]
    violations: list[str]    # supervisor findings; empty = pass
    final_response: str
    retry_count: int
