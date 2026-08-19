"""
Agentic retriever — a ReAct agent that decides how to search the statute corpus.

Replaces the deterministic retriever node's fixed "exact-lookup else vector
search" dispatch, so the LLM picks the tool, the arguments, and whether weak
results are worth searching again. Built on LangChain's create_agent.

Tools write their rows into the `retrieved_chunks` state channel rather than
into ToolMessage text, so results come back losslessly instead of via parsing.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from operator import add, or_

from langgraph.config import get_stream_writer
from typing_extensions import Annotated

from langchain.agents import AgentState as _ReactAgentState
from langchain.agents import create_agent

from agent.llm_factory import make_llm
from agent.retrieval.reference_graph import (
    FollowOnceGuard,
    RetrievalReferenceContext,
    empty_reference_metrics,
    follow_references_enabled,
    should_follow_references,
)
from agent.retrieval.tools import follow_references, lookup_section, search_statutes

logger = logging.getLogger(__name__)

# recursion_limit counts graph super-steps (agent + tool nodes), not tool calls.
# ~6 leaves room for two search rounds (agent→tool→agent→tool→agent) plus slack,
# while still bounding a misbehaving loop.
RECURSION_LIMIT = int(os.getenv("RETRIEVAL_RECURSION_LIMIT", "6"))

_SYSTEM = """You are the retrieval step of a Malaysian legal research assistant.
Your only job is to gather the statute sections needed to answer the user's
research question by calling the search tools. You do NOT write the final answer.

Choose tools deliberately:
- If the question names a specific section AND an Act (e.g. "section 90A of the
  Evidence Act", "seksyen 34 Kanun Keseksaan"), call `lookup_section` first.
- Otherwise, or if `lookup_section` returns nothing, call `search_statutes` with
  a concise natural-language query.
- If a search returns no sections or the results look off-topic, call
  `search_statutes` again ONCE with a reformulated query (broader wording or
  different keywords). Do not keep searching indefinitely.

Stop as soon as you have relevant sections. When you are done, reply with a
one-line note of what you found — do not answer the legal question yourself."""

_FOLLOW_REFERENCES_SYSTEM = _SYSTEM + """

When and only when `follow_references` is available:
- It is for explicit statutory-reference intent only: what an anchored provision
  refers to, is subject to/notwithstanding, which provisions refer to it, a
  definition explicitly located under another provision, or targeted retry
  feedback that says a directly referenced provision is missing.
- First establish the concrete anchor with `lookup_section` or
  `search_statutes`. Never call `follow_references` in the same tool-call batch
  as that initial lookup/search.
- Do not use it for an ordinary "what does section X say?", topical employment
  questions, broad research, unrelated Acts, or as a routine second step.
- Call it at most once. It follows only direct published outgoing/incoming edges,
  never a second hop, and returns at most five edges. Boundary targets cannot be
  expanded. A graph or target lookup failure means keep the existing evidence
  and stop or continue through the normal search path."""


def _dedupe_chunks(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
    """Repeated and broadened searches overlap heavily, so accumulate across tool
    calls without letting the same section land in the list twice."""
    merged: list[dict] = []
    seen: set[tuple] = set()
    for chunk in (left or []) + (right or []):
        key = (
            str(chunk.get("act_number", "")),
            str(chunk.get("section_number", "")).upper(),
            str(chunk.get("language", "")),
            str(chunk.get("document_id", "")),
            str(chunk.get("extraction_id", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return merged


class RetrievalState(_ReactAgentState):
    # Reducers rather than plain overwrites: one run makes several tool calls, and
    # each must add to what the earlier ones found instead of replacing it.
    retrieved_chunks: Annotated[list[dict], _dedupe_chunks]
    # Written by the tools themselves, so the trace records what actually ran
    # rather than what the model asked for. The tool_selection eval asserts order.
    tool_trace: Annotated[list[str], add]


def _merge_metrics(left: dict | None, right: dict | None) -> dict:
    merged = empty_reference_metrics()
    for source in (left or {}, right or {}):
        for key in merged:
            try:
                merged[key] += int(source.get(key, 0))
            except (TypeError, ValueError):
                continue
    return merged


class ReferenceRetrievalState(RetrievalState):
    reference_followed: Annotated[bool, or_]
    reference_trace: Annotated[list[dict], add]
    reference_metrics: Annotated[dict, _merge_metrics]


@lru_cache(maxsize=2)
def _build_retrieval_agent(follow_enabled: bool):
    """maxsize=2 so the two flag variants never share a compiled agent — a leaked
    tool list would bind follow_references while the flag is off."""
    model = make_llm(os.getenv("RETRIEVAL_AGENT_MODEL", "gpt-4.1"))
    tools = [search_statutes, lookup_section]
    system_prompt = _SYSTEM
    state_schema = RetrievalState
    kwargs = {}
    if follow_enabled:
        tools.append(follow_references)
        system_prompt = _FOLLOW_REFERENCES_SYSTEM
        state_schema = ReferenceRetrievalState
        kwargs["context_schema"] = RetrievalReferenceContext
    return create_agent(
        model,
        tools=tools,
        system_prompt=system_prompt,
        state_schema=state_schema,
        **kwargs,
    )


def get_retrieval_agent():
    """Reads the flag per call, not at import, so flipping the dark launch takes
    effect without a restart."""
    return _build_retrieval_agent(follow_references_enabled())


def run_retrieval_agent(query: str, feedback: str = "", config=None) -> dict:
    """Run the ReAct loop for one query.

    `feedback` comes from a re-retrieval pass so the agent can adjust its search.
    `config` is the parent graph's RunnableConfig; forwarding it is what lets the
    tools' stream writes reach the parent's stream. Raises on failure — the
    caller in agent/nodes/retriever.py decides whether to fail open.
    """
    request = query if not feedback else f"{query}\n\nRe-retrieval note: {feedback}"
    # Spreading keeps the parent's metadata/tags/callbacks so nested runs stay
    # filterable in LangSmith; recursion_limit and run_name are pinned so the
    # sub-loop stays bounded and doesn't inherit the parent's run name.
    invoke_config = {**(config or {}), "recursion_limit": RECURSION_LIMIT, "run_name": "retrieval_agent"}
    follow_enabled = follow_references_enabled()
    agent = _build_retrieval_agent(follow_enabled)
    agent_input = {"messages": [{"role": "user", "content": request}]}
    context = (
        RetrievalReferenceContext(
            follow_allowed=should_follow_references(query, feedback),
            follow_guard=FollowOnceGuard(),
        )
        if follow_enabled
        else None
    )

    # A manually invoked sub-agent's custom stream doesn't bubble up to the parent
    # graph, so when a parent stream is active we stream and re-emit each event
    # through the parent's writer rather than plain-invoking.
    parent_writer = None
    try:
        parent_writer = get_stream_writer()
    except Exception:
        parent_writer = None

    if parent_writer is None:
        if context is None:
            final_state = agent.invoke(agent_input, invoke_config)
        else:
            final_state = agent.invoke(agent_input, invoke_config, context=context)
    else:
        final_state = {}
        stream_kwargs = {"stream_mode": ["custom", "values"]}
        if context is not None:
            stream_kwargs["context"] = context
        for mode, chunk in agent.stream(agent_input, invoke_config, **stream_kwargs):
            if mode == "custom":
                parent_writer(chunk)
            else:  # "values" emits full snapshots, so the last one is final
                final_state = chunk

    result = {
        "chunks": final_state.get("retrieved_chunks", []),
        "tools": final_state.get("tool_trace", []),
    }
    if follow_enabled:
        result.update({
            "reference_trace": final_state.get("reference_trace", []),
            "reference_metrics": final_state.get(
                "reference_metrics",
                empty_reference_metrics(),
            ),
        })
    return result
