"""Query lifecycle for the Malaysian Legal Research Assistant."""
from __future__ import annotations

from collections.abc import AsyncIterator

from agent.nodes.retriever import retriever_node
from agent.nodes.router import router_node
from agent.nodes.supervisor import ESCALATION_RESPONSE, supervisor_node
from agent.nodes.synthesiser import synthesiser_node
from agent.state import AgentState, Message, QueryEvent, QueryResult

MAX_HISTORY_TURNS = 6
MAX_RETRIES = 1

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


def _run_once(state: AgentState) -> AgentState:
    state.update(router_node(state))
    if state.get("query_type") == "escalate":
        state["final_response"] = ESCALATION_RESPONSE
        state["violations"] = []
        state["citations"] = []
        return state

    state.update(retriever_node(state))
    state.update(synthesiser_node(state))
    state.update(supervisor_node(state))
    return state


def run_query(query: str, history: list[Message] | None = None) -> QueryResult:
    state = _initial_state(query, history)
    state = _run_once(state)

    while state.get("violations") and state.get("retry_count", 0) < MAX_RETRIES:
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["violations"] = []
        state.update(synthesiser_node(state))
        state.update(supervisor_node(state))

    return {
        "query_type": state.get("query_type", ""),
        "response": _response_text(state),
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
    }


async def run_query_stream(query: str, history: list[Message] | None = None) -> AsyncIterator[QueryEvent]:
    state = _initial_state(query, history)

    state.update(router_node(state))
    yield {"type": "status", "message": _STATUS_MESSAGES["router"]}
    if state.get("query_type") == "escalate":
        yield {
            "type": "response",
            "content": ESCALATION_RESPONSE,
            "citations": [],
            "violations": [],
        }
        return

    state.update(retriever_node(state))
    yield {"type": "status", "message": _STATUS_MESSAGES["retriever"]}

    state.update(synthesiser_node(state))
    yield {"type": "status", "message": _STATUS_MESSAGES["synthesiser"]}

    state.update(supervisor_node(state))
    yield {"type": "status", "message": _STATUS_MESSAGES["supervisor"]}

    while state.get("violations") and state.get("retry_count", 0) < MAX_RETRIES:
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["violations"] = []
        yield {"type": "status", "message": _STATUS_MESSAGES["increment_retry"]}
        state.update(synthesiser_node(state))
        yield {"type": "status", "message": _STATUS_MESSAGES["synthesiser"]}
        state.update(supervisor_node(state))
        yield {"type": "status", "message": _STATUS_MESSAGES["supervisor"]}

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
