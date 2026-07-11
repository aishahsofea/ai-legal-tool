"""
Retriever node — the deterministic retrieval path.

Embeds the query and searches pgvector for the top-k chunks, trying an exact
section lookup first for `statute_lookup` queries. The actual search lives in
agent/retrieval/search.py so the same functions back the agentic retrieval
tools; this node is the proven, non-agentic path kept as a fail-open fallback.

Searches English chunks (the cross-lingual embedding handles BM and mixed
queries). Each chunk carries the AGC PDF URL (with page anchor) for deep links.
"""
from agent.retrieval.search import (
    exact_section_lookup,
    extract_act_hint,
    extract_section_number,
    semantic_search,
)
from agent.state import AgentState


def retriever_node(state: AgentState) -> dict:
    # Search on the history-resolved Standalone Query when the contextualize node
    # produced one; otherwise fall back to the raw query (first turn / fail-open).
    query = state.get("standalone_query") or state["query"]

    rows: list[dict] = []
    if state.get("query_type") == "statute_lookup":
        section = extract_section_number(query)
        act_number, act_title = extract_act_hint(query)
        if section:
            rows = exact_section_lookup(section, act_number, act_title)
    if not rows:
        rows = semantic_search(query)

    return {"retrieved_chunks": rows}
