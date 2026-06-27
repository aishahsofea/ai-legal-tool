"""LangGraph agent graph for the Malaysian Legal Research Assistant.

The graph owns the full query lifecycle, including bounded retries:
router → retriever → synthesiser → citation_validator → grounding_check → supervisor
                                      ↑                               ↓
                                      └──── retry when violations ────┘
"""
import atexit
import contextlib
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.contextualize import contextualize_node
from agent.nodes.conversational import conversational_node
from agent.nodes.grounding_check import grounding_check_node
from agent.nodes.router import router_node
from agent.nodes.retriever import retriever_node
from agent.nodes.supervisor import ESCALATION_RESPONSE, supervisor_node
from agent.nodes.synthesiser import synthesiser_node
from agent.query_policy import MAX_RETRIES, delivered_response, strip_disclaimer
from agent.state import AgentState


def _route_from_router(state: AgentState) -> str:
    if state["query_type"] == "escalate":
        return END
    if state["query_type"] == "conversational":
        return "conversational"
    return "contextualize"


def _escalate_node(state: AgentState) -> dict:
    return {"final_response": ESCALATION_RESPONSE}


def _increment_retry_node(state: AgentState) -> dict:
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "violations": [],
    }


def _route_from_supervisor(state: AgentState) -> str:
    if state.get("violations") and state.get("retry_count", 0) < MAX_RETRIES:
        return "increment_retry"
    return END


def _start_turn(state: AgentState) -> dict:
    # Reset per-query fields so turn N does not inherit turn N-1's leftovers.
    # history is intentionally NOT reset (it accumulates via the reducer).
    return {
        "query_type": "",
        "standalone_query": "",
        "response_language": "en",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }


def _record_turn(state: AgentState) -> dict:
    # Append at the END so that DURING the turn, state["history"] holds prior turns only
    # (prevents the current query appearing twice in prompts).
    # Compute the delivered response once (safe fallback when violations remain) and use it
    # for BOTH the returned final_response and the stored assistant turn, so the checkpointed
    # history and what the user receives agree by construction — memory can never diverge.
    # Strip the appended disclaimer so stored history is free of repeated boilerplate;
    # the disclaimer still reaches the user via final_response (untouched here).
    delivered = delivered_response(state)
    return {
        "final_response": delivered,
        "history": [
            {"role": "user", "content": state["query"]},
            {"role": "assistant", "content": strip_disclaimer(delivered)},
        ],
    }


# Holds long-lived resources (e.g. the PostgresSaver connection pool) open for the
# process lifetime. PostgresSaver.from_conn_string is a context manager that yields the
# saver; we enter it here and close it at interpreter exit.
_checkpointer_stack = contextlib.ExitStack()
atexit.register(_checkpointer_stack.close)


def _make_checkpointer():
    db_url = os.getenv("DATABASE_URL")
    if not db_url or os.getenv("CHECKPOINTER", "").lower() == "memory":
        return MemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    cp = _checkpointer_stack.enter_context(PostgresSaver.from_conn_string(db_url))
    cp.setup()   # idempotent; creates checkpoint tables if absent
    return cp


def build_graph(checkpointer=None) -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("start_turn", _start_turn)
    g.add_node("router", router_node)
    g.add_node("escalate", _escalate_node)
    g.add_node("conversational", conversational_node)
    g.add_node("contextualize", contextualize_node)
    g.add_node("retriever", retriever_node)
    g.add_node("synthesiser", synthesiser_node)
    g.add_node("citation_validator", citation_validator_node)
    g.add_node("grounding_check", grounding_check_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("increment_retry", _increment_retry_node)
    g.add_node("record_turn", _record_turn)

    g.set_entry_point("start_turn")
    g.add_edge("start_turn", "router")

    g.add_conditional_edges("router", _route_from_router, {
        END: "escalate",
        "conversational": "conversational",
        "contextualize": "contextualize",
    })
    g.add_edge("escalate", "record_turn")
    g.add_edge("conversational", "record_turn")
    g.add_edge("contextualize", "retriever")
    g.add_edge("retriever", "synthesiser")
    g.add_edge("synthesiser", "citation_validator")
    g.add_edge("citation_validator", "grounding_check")
    g.add_edge("grounding_check", "supervisor")
    g.add_conditional_edges("supervisor", _route_from_supervisor, {
        "increment_retry": "increment_retry",
        END: "record_turn",
    })
    g.add_edge("increment_retry", "synthesiser")
    g.add_edge("record_turn", END)

    return g.compile(checkpointer=checkpointer)


# Module-level compiled graph — Phase 4 wires the real checkpointer in.
graph = build_graph(_make_checkpointer())


@contextlib.asynccontextmanager
async def lifespan_graph():
    """Async context manager yielding a graph for the FastAPI app's lifetime.

    `graph.astream()` needs a checkpointer with async support (`aget_tuple`/`aput`),
    which the sync `PostgresSaver` above does not implement. `AsyncPostgresSaver`'s
    connection is bound to the event loop it is created on, so it must be opened from
    within the server's running loop (e.g. a FastAPI lifespan handler) rather than at
    module-import time.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url or os.getenv("CHECKPOINTER", "").lower() == "memory":
        yield build_graph(MemorySaver())
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    async with AsyncPostgresSaver.from_conn_string(db_url) as cp:
        await cp.setup()
        yield build_graph(cp)
