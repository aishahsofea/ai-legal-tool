"""
Retrieval tools the agentic retriever binds (agent/retrieval/agent.py).

Each tool returns a ``Command`` that writes into the agent's state channels plus
a short ``ToolMessage``. That summary exists for the model, not for us — it is
what the model reads to judge hit quality and decide whether to search again.

A tool must never crash the ReAct loop, so DB and embedding errors come back as
a ToolMessage the model can act on instead of raising through the whole graph.
"""
from __future__ import annotations

import logging
import os
from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.config import get_stream_writer
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command
from typing_extensions import Annotated

from agent.feature_flags import flag_enabled
from agent.retrieval.reference_graph import (
    MAX_REFERENCE_EDGES,
    FollowOnceGuard,
    RetrievalReferenceContext,
    empty_reference_metrics,
    follow_published_references,
)
from agent.retrieval.search import exact_section_lookup, semantic_search
from agent.state import CommentaryNote
from agent.web_search import search_web

logger = logging.getLogger(__name__)


def _emit(name: str, summary: str) -> None:
    """Feeds the UI's PROCESS panel. Silent when no stream is active — a plain
    .invoke() (tests, evals) has no writer, and that is not an error."""
    try:
        get_stream_writer()({"tool_call": {"name": name, "summary": summary}})
    except Exception:
        pass


def _summarise(rows: list[dict]) -> str:
    """The model reads this to judge hit quality, so it names sections rather
    than only counting them."""
    if not rows:
        return "No sections found."
    heads = ", ".join(
        # A schedule row's section_number is empty (ADR 0018); its path
        # ("sched.2/para.1") is what names it instead. `path` already carries
        # the "s." prefix for a body row, so it's used as-is when present.
        f"{r.get('path') or 's.' + str(r.get('section_number') or '?')} of Act {r.get('act_number', '?')}"
        for r in rows[:5]
    )
    more = "" if len(rows) <= 5 else f" (+{len(rows) - 5} more)"
    return f"Found {len(rows)} section(s): {heads}{more}."


def _command(rows: list[dict], summary: str, tool_call_id: str, name: str) -> Command:
    """`name` is passed in rather than inferred so ``tool_trace`` records what
    actually ran, not what the model asked for."""
    return Command(
        update={
            "retrieved_chunks": rows,
            "tool_trace": [name],
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
        "tool_trace": ["follow_references"],
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
        return _command(
            [],
            f"search_statutes error for query '{query}'. Try a different query.",
            tool_call_id,
            "search_statutes",
        )
    return _command(rows, _summarise(rows), tool_call_id, "search_statutes")


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
        # Reuse the deterministic node's resolver so both paths accept the same
        # aliases.
        act_number, act_title = extract_act_hint(act)
        if not (act_number or act_title):
            act_number = act.strip()  # assume it was already an Act number

    try:
        rows = exact_section_lookup(section, act_number=act_number, act_title=act_title)
    except Exception:
        logger.warning("lookup_section failed", exc_info=True)
        return _command(
            [],
            f"lookup_section error for section '{section}'. Try search_statutes instead.",
            tool_call_id,
            "lookup_section",
        )

    if not rows:
        return _command(
            [],
            f"No exact match for section {section} in act '{act}'. Try search_statutes instead.",
            tool_call_id,
            "lookup_section",
        )
    return _command(rows, _summarise(rows), tool_call_id, "lookup_section")


def web_commentary_enabled() -> bool:
    return flag_enabled("WEB_COMMENTARY_ENABLED")


def _commentary_allowlist() -> list[str]:
    raw = os.getenv("COMMENTARY_ALLOWLIST", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _commentary_note(result: dict) -> CommentaryNote:
    return CommentaryNote(
        url=result["url"],
        title=result["title"],
        publisher=result["domain"],
        published_date=result["published_date"],
        retrieved_at=result["retrieved_at"],
        snippet=result["snippet"],
    )


def _commentary_summary(result: dict) -> str:
    if result["status"] != "ok":
        return (
            f"search_commentary error ({result['reason']}); continue with the "
            "existing search/lookup evidence."
        )
    notes = result["results"]
    if not notes:
        return "No commentary found from allowlisted publishers for this query."
    heads = ", ".join(f"{n['title'] or n['url']} ({n['domain']})" for n in notes[:5])
    more = "" if len(notes) <= 5 else f" (+{len(notes) - 5} more)"
    return f"Found {len(notes)} commentary note(s): {heads}{more}."


@tool
def search_commentary(
    query: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    max_results: int = 5,
) -> Command:
    """Search allowlisted legal-commentary publishers for background material.

    Returns practitioner-facing explanatory content — firm briefings, client
    alerts, and similar secondary commentary — from a small, operator-curated
    allowlist of trusted publishers. This is never statute text and never a
    citation: results are carried on a separate ``commentary`` channel and can
    never satisfy citation presence or be treated as authoritative. Use it
    only for background beyond what a bare section number tells you — for
    example how practitioners describe the practical effect of a provision —
    and only alongside or after ``lookup_section`` / ``search_statutes`` has
    established the statutory basis. Never use it as a substitute for those
    tools, and never use it for an ordinary "what does section X say?"
    question. A domain outside the allowlist is dropped before you see it. If
    results look weak or off-topic, you may call again once with a
    reformulated `query`.

    Args:
        query: Natural-language search text. Reformulate and retry on weak hits.
        max_results: Max commentary notes to return (default 5).
    """
    _emit("search_commentary", f"Searching commentary: “{query}”")
    result = search_web(query, _commentary_allowlist(), max_results=max_results)
    notes = [_commentary_note(row) for row in result["results"]] if result["status"] == "ok" else []
    return Command(
        update={
            "commentary": notes,
            "tool_trace": ["search_commentary"],
            "messages": [ToolMessage(_commentary_summary(result), tool_call_id=tool_call_id)],
        }
    )
