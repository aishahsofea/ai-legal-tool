"""Query lifecycle for the Malaysian Legal Research Assistant."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

from langchain_core.tracers.run_collector import RunCollectorCallbackHandler

from agent.graph import graph
from agent.memory.extractor import schedule_extraction
from agent.memory.pruner import schedule_pruning
from agent.observability import emit_feedback, root_run_id
from agent.query_policy import delivered_response, strip_disclaimer
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


def _flag(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def _config(
    thread_id: str,
    user_id: str | None = None,
    collector: RunCollectorCallbackHandler | None = None,
    source: str = "api",
) -> dict:
    # user_id scopes cross-thread Semantic Memory (ADR 0010). It rides in
    # `configurable` so any node can read it via its RunnableConfig without
    # threading it through AgentState. Nodes must treat it as optional.
    #
    # metadata/tags/run_name are standard RunnableConfig keys that LangChain
    # forwards to LangSmith automatically — they make traces filterable by
    # practitioner and feature-flag state (no SDK call needed). `source`
    # separates eval traffic from live API traffic in the dashboard.
    memory_checkpointer = not os.getenv("DATABASE_URL") or os.getenv("CHECKPOINTER", "").lower() == "memory"
    metadata = {
        "thread_id": thread_id,
        "user_id": user_id or "anonymous",
        "source": source,
        "agentic_retrieval": _flag("AGENTIC_RETRIEVAL"),
        "semantic_recall": _flag("SEMANTIC_MEMORY_RECALL"),
        "semantic_extract": _flag("SEMANTIC_MEMORY_EXTRACT"),
        "checkpointer": "memory" if memory_checkpointer else "postgres",
    }
    flag_tags = [k for k in ("agentic_retrieval", "semantic_recall", "semantic_extract") if metadata[k]]
    config: dict = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "metadata": metadata,
        "tags": ["legal_query", f"source:{source}", *flag_tags],
        "run_name": "legal_query",
    }
    if collector is not None:
        config["callbacks"] = [collector]
    return config


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
    # Sync path is eval-only (evals/run_evals.py); tag it `source=eval` so eval
    # runs stay separable from live traffic in the LangSmith dashboard.
    collector = RunCollectorCallbackHandler()
    state = graph.invoke(_turn_input(query), _config(thread_id, user_id, collector, source="eval"))
    state = _fail_closed_if_violations(state)
    emit_feedback(root_run_id(collector), state)

    return {
        "query_type": state.get("query_type", ""),
        "response": _response_text(state),
        "citations": state.get("citations", []),
        "violations": state.get("violations", []),
        "tool_trace": state.get("tool_trace", []),
    }


async def run_query_stream(query: str, thread_id: str, user_id: str | None = None) -> AsyncIterator[QueryEvent]:
    collector = RunCollectorCallbackHandler()
    config = _config(thread_id, user_id, collector, source="api")
    state: dict = {}
    # "updates" carries node outputs (for per-node status); "custom" carries the
    # tool-call events the retrieval agent's tools write via get_stream_writer
    # (agent/retrieval/tools.py). With multiple modes each item is (mode, chunk).
    async for mode, chunk in graph.astream(
        _turn_input(query), config, stream_mode=["updates", "custom"]
    ):
        if mode == "custom":
            tool_call = chunk.get("tool_call") if isinstance(chunk, dict) else None
            if tool_call:
                yield {
                    "type": "tool_call",
                    "name": tool_call.get("name", ""),
                    "summary": tool_call.get("summary", ""),
                }
            continue

        # mode == "updates"
        update = chunk
        node_name = next(iter(update.keys()), "")
        # A node that makes no state change (e.g. recall no-oping on an empty store)
        # surfaces in the updates stream as {node: None}, so coerce None → {}.
        node_output = next(iter(update.values()), None) or {}
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

    # Emit LangSmith feedback HERE — after the astream loop completes (so `state`
    # is whole) and BEFORE the response yield. Code after a `yield` in an async
    # generator is skipped if the consumer disconnects early, which would silently
    # drop feedback; emitting pre-yield guarantees it runs on normal completion.
    # Non-blocking (trace_id-batched) and fail-open, so it never delays tokens.
    emit_feedback(root_run_id(collector), state)

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

    # Semantic Memory write path (ADR 0010, extended by ADR 0012): extract in the
    # background after the response is delivered. Runs on legal AND conversational turns
    # — the latter is where a practitioner states their own background ("I'm a software
    # engineer"), which is now a durable fact worth remembering. Excludes only the
    # error/empty state and escalate (a fixed hand-off with nothing durable to extract).
    # Disclaimer stripped so the extractor sees the answer, not boilerplate; gating +
    # fail-open live in the callee.
    if state.get("query_type") not in ("", "escalate"):
        schedule_extraction(graph.store, user_id, query, strip_disclaimer(final))
        # Consolidate + cap the store off the hot path (ADR 0010, Phase 4). Independent
        # of extraction (eventual consistency); size-debounced and fail-open in the callee.
        schedule_pruning(graph.store, user_id)
