"""
Clarify node — the graph's one human-in-the-loop pause (ADR 0015).

When the router judges a query un-actionable without a missing detail (a section
number with no Act, say), it sets `clarifying_question` and routes here. This node
calls LangGraph's `interrupt()`: the graph suspends, the question surfaces to the
caller over SSE, and execution resumes only when the caller replies with
`Command(resume=<answer>)` on the same thread_id.

This is *graph-initiated* pause — distinct from the *user-initiated* barge-in
cancellation of ADR 0014. The two reuse the same same-thread continuation but are
different mechanisms (one pauses for input, the other aborts a run).

Design notes:
  - The node is side-effect-free before the interrupt, which the re-execution rule
    demands: a resumed node re-runs from the top, so any pre-interrupt side effect
    would fire twice.
  - On resume it MERGES the original query with the answer into one self-contained
    query (option C), rather than letting the bare answer overwrite the query. The
    original intent ("section 5") lives only in state["query"]; the answer ("the
    Contracts Act 1950") lives only in the resume value. Retrieval reads query /
    standalone_query — not the interrupt exchange — so without the merge the turn
    would retrieve on the answer alone and lose the original intent. String-merge to
    start; an LLM merge is the drop-in upgrade path.
  - `clarified` is set so the router branch cannot ask a second time this turn.
"""
from langgraph.types import interrupt

from agent.state import AgentState


def _merge(query: str, answer: str) -> str:
    # Fold the clarification back into one self-contained query. Keeping the original
    # verbatim preserves section/Act tokens the retriever matches on.
    answer = (answer or "").strip()
    if not answer:
        return query
    return f"{query} (clarified: {answer})"


def clarify_node(state: AgentState) -> dict:
    answer = interrupt({
        "type": "clarification",
        "question": state.get("clarifying_question", ""),
    })
    return {
        "query": _merge(state["query"], answer if isinstance(answer, str) else str(answer)),
        "clarifying_question": "",
        "clarified": True,
        "query_type": "",   # force re-classification of the merged query by the router
    }
