"""Query lifecycle for the Malaysian Legal Research Assistant."""
from __future__ import annotations

from collections.abc import AsyncIterator

from agent.graph import graph
from agent.query_policy import delivered_response
from agent.state import AgentState, QueryEvent, QueryResult

_STATUS_MESSAGES = {
    "router": "Classifying query...",
    "contextualize": "Resolving follow-up...",
    "retriever": "Searching Malaysian Acts...",
    "synthesiser": "Drafting response...",
    "supervisor": "Checking policy compliance...",
    "increment_retry": "Refining response...",
    "escalate": "Escalating to human lawyer...",
    "conversational": "Responding...",
}


def _turn_input(query: str) -> dict:
    # The start_turn node fills in the rest of the per-turn fields; the
    # checkpointer supplies accumulated history keyed by thread_id.
    return {"query": query}


def _config(thread_id: str, user_id: str | None = None) -> dict:
    # user_id scopes cross-thread Semantic Memory (ADR 0010). It rides in
    # `configurable` so any node can read it via its RunnableConfig without
    # threading it through AgentState. Nodes must treat it as optional.
    return {"configurable": {"thread_id": thread_id, "user_id": user_id}}


def set_graph(g) -> None:
    """Swap the graph used by run_query/run_query_stream.

    Used during FastAPI startup to install a graph backed by AsyncPostgresSaver,
    which must be built inside the server's running event loop (see
    agent.graph.lifespan_graph).
    """
    global graph
    graph = g


def _response_text(state: dict) -> str:
    return state.get("final_response") or state.get("draft_response") or ""


def _fail_closed_if_violations(state: AgentState) -> AgentState:
    """Replace any known non-compliant final draft with a safe fallback.

    Defensive net: the graph's record_turn already sets final_response to the
    delivered value, but this also covers the escalate path and any direct callers.
    Expressed via the shared helper so the two code paths can no longer drift.
    """
    state["final_response"] = delivered_response(state)
    return state


def run_query(query: str, thread_id: str, user_id: str | None = None) -> QueryResult:
    state = graph.invoke(_turn_input(query), _config(thread_id, user_id))
    state = _fail_closed_if_violations(state)

    return {
        "query_type": state.get("query_type", ""),
        "response": _response_text(state),
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
    }


async def run_query_stream(query: str, thread_id: str, user_id: str | None = None) -> AsyncIterator[QueryEvent]:
    config = _config(thread_id, user_id)
    state: dict = {}
    async for update in graph.astream(_turn_input(query), config, stream_mode="updates"):
        node_name = next(iter(update.keys()), "")
        node_output = next(iter(update.values()), {})
        if node_name == "contextualize":
            # Only announce a rewrite when one actually happened — non-empty and
            # different from the raw query. Never surface the rewritten text.
            standalone = node_output.get("standalone_query", "")
            if standalone and standalone != query:
                yield {"type": "status", "message": _STATUS_MESSAGES["contextualize"]}
        elif node_name in _STATUS_MESSAGES:
            yield {"type": "status", "message": _STATUS_MESSAGES[node_name]}
        state.update(node_output)

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
