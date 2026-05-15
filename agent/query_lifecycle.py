"""Query lifecycle for the Malaysian Legal Research Assistant."""
from __future__ import annotations

from collections.abc import AsyncIterator

from agent.graph import graph
from agent.query_policy import FINAL_FAILURE_RESPONSE, MAX_HISTORY_TURNS
from agent.state import AgentState, Message, QueryEvent, QueryResult

_STATUS_MESSAGES = {
    "router": "Classifying query...",
    "retriever": "Searching Malaysian Acts...",
    "synthesiser": "Drafting response...",
    "supervisor": "Checking policy compliance...",
    "increment_retry": "Refining response...",
    "escalate": "Escalating to human lawyer...",
}


def trim_history(history: list[Message] | None, limit: int = MAX_HISTORY_TURNS) -> list[Message]:
    if not history:
        return []
    return history[-limit:]


def _initial_state(query: str, history: list[Message] | None = None) -> AgentState:
    return {
        "query": query,
        "history": trim_history(history),
        "query_type": "",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }


def _response_text(state: dict) -> str:
    return state.get("final_response") or state.get("draft_response") or ""


def _fail_closed_if_violations(state: AgentState) -> AgentState:
    """Replace any known non-compliant final draft with a safe fallback."""
    if state.get("violations"):
        state["final_response"] = FINAL_FAILURE_RESPONSE
    return state


def run_query(query: str, history: list[Message] | None = None) -> QueryResult:
    state = graph.invoke(_initial_state(query, history))
    state = _fail_closed_if_violations(state)

    return {
        "query_type": state.get("query_type", ""),
        "response": _response_text(state),
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
    }


async def run_query_stream(query: str, history: list[Message] | None = None) -> AsyncIterator[QueryEvent]:
    state = _initial_state(query, history)
    async for update in graph.astream(state, stream_mode="updates"):
        node_name = next(iter(update.keys()), "")
        if node_name in _STATUS_MESSAGES:
            yield {"type": "status", "message": _STATUS_MESSAGES[node_name]}
        state.update(next(iter(update.values()), {}))

    state = _fail_closed_if_violations(state)

    final = _response_text(state)
    if not final:
        yield {"type": "error", "message": "No response generated."}
        return

    yield {
        "type": "response",
        "content": final,
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
    }
