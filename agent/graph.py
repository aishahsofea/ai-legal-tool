"""LangGraph agent graph for the Malaysian Legal Research Assistant.

The graph owns the full query lifecycle, including bounded retries:
router → retriever → synthesiser → citation_validator → grounding_check → supervisor
                                      ↑                               ↓
                                      └──── retry when violations ────┘
"""
import atexit
import contextlib
import os
from functools import lru_cache

from langgraph._internal._runnable import RunnableCallable
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore

from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.clarify import clarify_node
from agent.nodes.contextualize import acontextualize_node, contextualize_node
from agent.nodes.conversational import aconversational_node, conversational_node
from agent.nodes.grounding_check import agrounding_check_node, grounding_check_node
from agent.nodes.recall import arecall_node, recall_node
from agent.nodes.router import arouter_node, router_node
from agent.nodes.retriever import agentic_retriever_node, retriever_node
from agent.nodes.supervisor import ESCALATION_RESPONSE, supervisor_node
from agent.nodes.synthesiser import asynthesiser_node, synthesiser_node
from agent.query_policy import MAX_RETRIES, delivered_response, strip_disclaimer
from agent.state import AgentState


def _route_from_router(state: AgentState) -> str:
    if state["query_type"] == "escalate":
        return END
    if state["query_type"] == "conversational":
        return "conversational"
    # Clarify only when the router actually produced a question AND we have not already
    # asked one this turn — an empty question or a second ambiguity falls through to the
    # normal legal path rather than pausing on nothing or looping (ADR 0015).
    if (
        state["query_type"] == "clarify"
        and state.get("clarifying_question")
        and not state.get("clarified")
    ):
        return "clarify"
    return "contextualize"


def _escalate_node(state: AgentState) -> dict:
    return {"final_response": ESCALATION_RESPONSE}


def _increment_retry_node(state: AgentState) -> dict:
    # Re-draft path: clear findings and re-run the synthesiser against the same
    # retrieved chunks (a policy/phrasing fix). Feedback is cleared so a stale
    # re-retrieval note can't leak into a subsequent turn.
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "violations": [],
        "evidence_violations": [],
        "retrieval_feedback": "",
    }


def _build_retrieval_feedback(evidence_violations: list[str]) -> str:
    joined = " ".join(evidence_violations)
    return (
        "The previous answer had missing or unsupported citations: "
        f"{joined} Search for statute sections that directly address these points."
    )


def _retry_retrieve_node(state: AgentState) -> dict:
    # Re-retrieve path: an evidence gap (bad/missing citation, unsupported claim)
    # is better fixed by fetching different sources than by re-drafting the same
    # ones. Bump the retry, clear findings, and hand the retrieval agent feedback.
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "violations": [],
        "evidence_violations": [],
        "retrieval_feedback": _build_retrieval_feedback(state.get("evidence_violations", [])),
    }


def _agentic_retrieval_enabled() -> bool:
    return os.getenv("AGENTIC_RETRIEVAL", "").lower() in ("1", "true", "yes")


def _route_from_supervisor(state: AgentState) -> str:
    if state.get("violations") and state.get("retry_count", 0) < MAX_RETRIES:
        # Evidence gaps re-retrieve (only meaningful with the agentic retriever,
        # which can act on feedback); policy/phrasing issues re-draft. With the
        # deterministic retriever a re-retrieve just repeats the same search, so
        # we keep the existing re-draft behaviour when the flag is off.
        if state.get("evidence_violations") and _agentic_retrieval_enabled():
            return "retry_retrieve"
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
        "evidence_violations": [],
        "recalled_memory": "",
        "retrieval_feedback": "",
        "tool_trace": [],
        "final_response": "",
        "retry_count": 0,
        "clarifying_question": "",
        "clarified": False,
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


# Holds long-lived resources (the PostgresSaver / PostgresStore connection pools) open
# for the process lifetime. Both from_conn_string helpers are context managers that
# yield the resource; we enter them here and close them at interpreter exit.
_resource_stack = contextlib.ExitStack()
atexit.register(_resource_stack.close)


def _make_checkpointer():
    db_url = os.getenv("DATABASE_URL")
    if not db_url or os.getenv("CHECKPOINTER", "").lower() == "memory":
        return MemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    cp = _resource_stack.enter_context(PostgresSaver.from_conn_string(db_url))
    cp.setup()   # idempotent; creates checkpoint tables if absent
    return cp


@lru_cache(maxsize=1)
def _openai_client():
    from openai import OpenAI
    return OpenAI()


def _embed_texts(texts: list[str]) -> list[list[float]]:
    # Same embedding model as the retriever (agent/nodes/retriever.py) so recall and
    # retrieval share one vector space. Called lazily by the store on search/put only —
    # never at import time, and never on the default path where recall is flagged off.
    resp = _openai_client().embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in resp.data]


# text-embedding-3-small → 1536 dims. Backs cross-thread semantic search over the store.
_STORE_INDEX = {"dims": 1536, "embed": _embed_texts}


def _make_store():
    """Cross-thread BaseStore for Semantic Memory, mirroring _make_checkpointer.

    Falls back to InMemoryStore when DATABASE_URL is unset or CHECKPOINTER=memory,
    exactly like the MemorySaver fallback. Written by agent/memory/extractor.py,
    read by the recall node.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url or os.getenv("CHECKPOINTER", "").lower() == "memory":
        return InMemoryStore(index=_STORE_INDEX)
    from langgraph.store.postgres import PostgresStore
    store = _resource_stack.enter_context(PostgresStore.from_conn_string(db_url, index=_STORE_INDEX))
    store.setup()   # idempotent; creates store tables if absent
    return store


def _select_retriever_node():
    """Pick the retrieval node by flag. AGENTIC_RETRIEVAL swaps the deterministic
    retriever for the ReAct agent (agent/retrieval/agent.py); the "retriever" node
    id and its edges are unchanged, and the agent wrapper fails open to the
    deterministic path so the graph shape and safety net are preserved."""
    if os.getenv("AGENTIC_RETRIEVAL", "").lower() in ("1", "true", "yes"):
        return agentic_retriever_node
    return retriever_node


def build_graph(checkpointer=None, store=None) -> StateGraph:
    g = StateGraph(AgentState)

    # LLM nodes are registered as sync+async twins (RunnableCallable): astream awaits
    # the async twin so a barge-in (cancellation) tears down the in-flight model call,
    # while graph.invoke (the eval path) uses the sync twin. Pure-Python nodes
    # (supervisor, citation_validator, start/record_turn, escalate) need no twin.
    g.add_node("start_turn", _start_turn)
    g.add_node("router", RunnableCallable(router_node, arouter_node, name="router"))
    # Human-in-the-loop pause (ADR 0015). Pure until its interrupt() call, so it is safe
    # under the re-execution rule; no async twin — interrupt() is not an awaited model
    # call, so there is nothing for a barge-in to tear down.
    g.add_node("clarify", clarify_node)
    g.add_node("escalate", _escalate_node)
    g.add_node("conversational", RunnableCallable(conversational_node, aconversational_node, name="conversational"))
    g.add_node("contextualize", RunnableCallable(contextualize_node, acontextualize_node, name="contextualize"))
    g.add_node("retriever", _select_retriever_node())
    g.add_node("recall", RunnableCallable(recall_node, arecall_node, name="recall"))
    # A second recall instance for the conversational short-circuit. Same pure read
    # functions (flag-gated, fail-open), but its out-edge feeds the conversational node
    # instead of the synthesiser — so remembered preferences also inform small talk
    # without touching the proven legal path's wiring (ADR 0010).
    g.add_node(
        "recall_conversational",
        RunnableCallable(recall_node, arecall_node, name="recall_conversational"),
    )
    g.add_node("synthesiser", RunnableCallable(synthesiser_node, asynthesiser_node, name="synthesiser"))
    g.add_node("citation_validator", citation_validator_node)
    g.add_node("grounding_check", RunnableCallable(grounding_check_node, agrounding_check_node, name="grounding_check"))
    g.add_node("supervisor", supervisor_node)
    g.add_node("increment_retry", _increment_retry_node)
    g.add_node("retry_retrieve", _retry_retrieve_node)
    g.add_node("record_turn", _record_turn)

    g.set_entry_point("start_turn")
    g.add_edge("start_turn", "router")

    g.add_conditional_edges("router", _route_from_router, {
        END: "escalate",
        "conversational": "recall_conversational",
        "contextualize": "contextualize",
        "clarify": "clarify",
    })
    # After the user answers, re-classify the merged, now self-contained query. The
    # `clarified` flag set by the node stops a second pause this turn (see _route_from_router).
    g.add_edge("clarify", "router")
    g.add_edge("escalate", "record_turn")
    g.add_edge("recall_conversational", "conversational")
    g.add_edge("conversational", "record_turn")
    g.add_edge("contextualize", "retriever")
    g.add_edge("retriever", "recall")
    g.add_edge("recall", "synthesiser")
    g.add_edge("synthesiser", "citation_validator")
    g.add_edge("citation_validator", "grounding_check")
    g.add_edge("grounding_check", "supervisor")
    g.add_conditional_edges("supervisor", _route_from_supervisor, {
        "increment_retry": "increment_retry",
        "retry_retrieve": "retry_retrieve",
        END: "record_turn",
    })
    g.add_edge("increment_retry", "synthesiser")
    # Re-retrieval re-enters the retrieve→recall→synthesise subpath with feedback.
    g.add_edge("retry_retrieve", "retriever")
    g.add_edge("record_turn", END)

    return g.compile(checkpointer=checkpointer, store=store)


# Module-level compiled graph — Phase 4 wires the real checkpointer in.
graph = build_graph(_make_checkpointer(), _make_store())


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
        yield build_graph(MemorySaver(), InMemoryStore(index=_STORE_INDEX))
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore
    # Both bind to the running loop, so both are opened here (not at import time).
    async with (
        AsyncPostgresSaver.from_conn_string(db_url) as cp,
        AsyncPostgresStore.from_conn_string(db_url, index=_STORE_INDEX) as store,
    ):
        await cp.setup()
        await store.setup()
        yield build_graph(cp, store)
