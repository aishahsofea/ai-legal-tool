"""
Retrieval tools the agentic retriever binds (agent/retrieval/agent.py).

Each tool wraps a function from agent/retrieval/search.py and returns a
``Command`` that merges the found chunks into the agent's ``retrieved_chunks``
state channel (see RetrievalState), plus a short ``ToolMessage`` summary the
model reads to judge hit quality and decide whether to search again.

Reliability: a tool must never crash the ReAct loop. DB/embedding errors are
caught and reported back as a ToolMessage so the model can retry or stop rather
than the whole graph raising.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.config import get_stream_writer
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command
from typing_extensions import Annotated

from agent.retrieval.reference_graph import (
    MAX_REFERENCE_EDGES,
    FollowOnceGuard,
    RetrievalReferenceContext,
    empty_reference_metrics,
    follow_published_references,
)
from agent.retrieval.search import exact_section_lookup, semantic_search

logger = logging.getLogger(__name__)


def _emit(name: str, summary: str) -> None:
    """Surface a tool call on the graph's custom stream so the UI can show it as a
    PROCESS step. A no-op when no stream is active (e.g. .invoke() in tests)."""
    try:
        get_stream_writer()({"tool_call": {"name": name, "summary": summary}})
    except Exception:
        pass


def _summarise(rows: list[dict]) -> str:
    """One-line, model-readable summary of a result set."""
    if not rows:
        return "No sections found."
    heads = ", ".join(
        f"s.{r.get('section_number', '?')} of Act {r.get('act_number', '?')}"
        for r in rows[:5]
    )
    more = "" if len(rows) <= 5 else f" (+{len(rows) - 5} more)"
    return f"Found {len(rows)} section(s): {heads}{more}."


def _command(rows: list[dict], summary: str, tool_call_id: str) -> Command:
    return Command(
        update={
            "retrieved_chunks": rows,
            "messages": [ToolMessage(summary, tool_call_id=tool_call_id)],
        }
    )


def _reference_summary(result: dict) -> str:
    status = result.get("status", "skipped")
    reason = result.get("reason", "unknown")
    metrics = result.get("metrics", {})
    if status == "followed":
        targets = ", ".join(
            f"{target.get('provision_id', '?')} ({target.get('lookup_status', 'unknown')})"
            for target in result.get("targets", [])[:MAX_REFERENCE_EDGES]
        )
        suffix = f" Targets: {targets}." if targets else ""
        return (
            "Published one-hop reference follow completed: "
            f"{metrics.get('edges_returned', 0)} edge(s), "
            f"{metrics.get('targets_resolved', 0)} citable target(s), "
            f"{metrics.get('targets_failed', 0)} lookup failure(s), and "
            f"{metrics.get('boundary_targets', 0)} boundary target(s)."
            f"{suffix}"
        )
    if status == "graph_unavailable":
        return (
            "Published reference graph unavailable "
            f"({reason}); continue with the existing search/lookup evidence."
        )
    return (
        f"Reference follow skipped ({reason}); continue with the existing "
        "search/lookup evidence."
    )


def _guard_from_context(context) -> FollowOnceGuard | None:
    if isinstance(context, dict):
        guard = context.get("follow_guard")
        return guard if isinstance(guard, FollowOnceGuard) else None
    return None


def _skipped_follow(reason: str) -> dict:
    metrics = empty_reference_metrics()
    metrics.update({"calls": 1, "skipped": 1})
    return {
        "status": "skipped",
        "reason": reason,
        "chunks": [],
        "metrics": metrics,
    }


@tool
def follow_references(
    act: str,
    provision: str,
    runtime: ToolRuntime[RetrievalReferenceContext, dict],
    direction: Literal["outgoing", "incoming", "both"] = "outgoing",
    relationship_kinds: list[str] | None = None,
    max_edges: int = MAX_REFERENCE_EDGES,
    document_id: str | None = None,
) -> Command:
    """Follow direct, published statutory references from one exact retrieved anchor.

    Use this only for explicit reference intent (what a provision refers to, is
    subject to/notwithstanding, what refers to it, or a definition explicitly
    located elsewhere), and only after ``lookup_section`` or ``search_statutes``
    has returned the anchor section. Never use it for an ordinary exact lookup,
    a topical/broad question, or as a default second search. One call is allowed
    per retrieval run; results are one hop and at most five published edges.

    Args:
        act: Anchor Act number or recognized Act name/alias.
        provision: Anchor section/provision, such as ``60D`` or ``section 60D``.
        direction: Direct outgoing, incoming, or both edges.
        relationship_kinds: Optional existing graph relationship literals only.
        max_edges: Requested edge bound; execution hard-caps this at five.
        document_id: Optional exact document ID already present on the retrieved
            anchor. Omit it to let execution resolve the unique exact chunk.
    """
    state = runtime.state if isinstance(runtime.state, dict) else {}
    context = runtime.context
    guard = _guard_from_context(context)
    if state.get("reference_followed") or guard is None or not guard.claim():
        result = _skipped_follow("already_followed_this_run")
    else:
        follow_allowed = (
            bool(context.get("follow_allowed"))
            if isinstance(context, dict)
            else False
        )
        if not follow_allowed:
            result = _skipped_follow("intent_not_selective")
        else:
            result = follow_published_references(
                act=act,
                provision=provision,
                retrieved_chunks=state.get("retrieved_chunks", []),
                direction=direction,
                relationship_kinds=relationship_kinds,
                max_edges=max_edges,
                document_id=document_id,
            )

    summary = _reference_summary(result)
    _emit(
        "follow_references",
        "Following direct published statutory references",
    )
    trace = {
        key: value
        for key, value in result.items()
        if key not in {"chunks", "metrics"}
    }
    return Command(update={
        "retrieved_chunks": result.get("chunks", []),
        "reference_followed": True,
        "reference_trace": [trace],
        "reference_metrics": result.get("metrics", empty_reference_metrics()),
        "messages": [ToolMessage(
            summary,
            tool_call_id=runtime.tool_call_id or "follow_references",
        )],
    })


@tool
def search_statutes(
    query: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    top_k: int = 8,
    act: str | None = None,
    language: str | None = None,
) -> Command:
    """Semantic search over Malaysian statute sections by meaning.

    Use this for topical or conceptual questions ("which laws cover data privacy
    for employers?") and whenever you do NOT already know the exact section
    number. If the first results look weak or empty, call again with a
    reformulated `query` (broader or with different keywords).

    Args:
        query: Natural-language search text. Reformulate and retry on weak hits.
        top_k: Max sections to return (default 8).
        act: Optional Act number to restrict the search (e.g. "56").
        language: Optional language filter, "en" or "bm".
    """
    _emit("search_statutes", f"Searching statutes: “{query}”")
    try:
        rows = semantic_search(query, top_k=top_k, act_number=act, language=language)
    except Exception:
        logger.warning("search_statutes failed", exc_info=True)
        return _command([], f"search_statutes error for query '{query}'. Try a different query.", tool_call_id)
    return _command(rows, _summarise(rows), tool_call_id)


@tool
def lookup_section(
    section: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    act: str | None = None,
) -> Command:
    """Exact lookup of a specific statute section within an Act.

    Use this when the question names a specific section, e.g. "what does section
    90A of the Evidence Act say?". Provide the section number and an Act hint (an
    Act number like "56", or a name/alias like "Evidence Act" or "Penal Code").
    Returns nothing if the section/Act can't be matched exactly — fall back to
    `search_statutes` in that case.

    Args:
        section: Section number, e.g. "90A".
        act: Act number ("56") or a name/alias ("Evidence Act", "PDPA").
    """
    _emit("lookup_section", f"Looking up section {section}" + (f" of {act}" if act else ""))
    from agent.retrieval.search import extract_act_hint

    act_number, act_title = (None, None)
    if act:
        # Accept either a bare number or a name/alias by reusing the same resolver
        # the deterministic node uses.
        act_number, act_title = extract_act_hint(act)
        if not (act_number or act_title):
            act_number = act.strip()  # assume it was already an Act number

    try:
        rows = exact_section_lookup(section, act_number=act_number, act_title=act_title)
    except Exception:
        logger.warning("lookup_section failed", exc_info=True)
        return _command([], f"lookup_section error for section '{section}'. Try search_statutes instead.", tool_call_id)

    if not rows:
        return _command(
            [],
            f"No exact match for section {section} in act '{act}'. Try search_statutes instead.",
            tool_call_id,
        )
    return _command(rows, _summarise(rows), tool_call_id)
