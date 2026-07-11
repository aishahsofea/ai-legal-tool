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

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from typing_extensions import Annotated

from agent.retrieval.search import exact_section_lookup, semantic_search

logger = logging.getLogger(__name__)


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
