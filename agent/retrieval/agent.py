"""
Agentic retriever — a ReAct agent that decides how to search the statute corpus.

Replaces the deterministic retriever node's fixed "exact-lookup else vector
search" dispatch with an LLM that binds two retrieval tools (search_statutes,
lookup_section) and chooses which to call, with what arguments, and whether to
search again on weak results. Built on langgraph's create_react_agent prebuilt.

How the loop runs (what the prebuilt abstracts):
  agent(LLM.bind_tools) → tools_condition → ToolNode → back to agent → …
The LLM emits a tool call, the ToolNode runs it and appends a ToolMessage, the
LLM sees the result and either calls another tool or stops. Our tools also write
their rows into the `retrieved_chunks` state channel via Command(update=...), so
after the loop we read them back losslessly instead of parsing ToolMessage text.
The loop is bounded by RECURSION_LIMIT so it can never spin forever.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from operator import add, or_

from langgraph.config import get_stream_writer
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState as _ReactAgentState
from typing_extensions import Annotated

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
    """Reducer for the retrieved_chunks channel: accumulate across tool calls,
    keeping the first-seen chunk per exact document/extraction/section identity."""
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
    # `messages` (with add_messages) comes from the base ReAct AgentState. We add a
    # side channel the tools write their found rows into, with a dedupe reducer so
    # repeated/overlapping searches accumulate cleanly.
    retrieved_chunks: Annotated[list[dict], _dedupe_chunks]
    # Each tool appends its own name as it runs, so the trace is a record of what
    # executed rather than a re-reading of the message list. Order is preserved by
    # `add`; the tool_selection eval asserts on it.
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
    """Compile one disabled/enabled variant without leaking tools across flags."""
    model = make_llm(os.getenv("RETRIEVAL_AGENT_MODEL", "gpt-4.1"))
    tools = [search_statutes, lookup_section]
    prompt = _SYSTEM
    state_schema = RetrievalState
    kwargs = {}
    if follow_enabled:
        tools.append(follow_references)
        prompt = _FOLLOW_REFERENCES_SYSTEM
        state_schema = ReferenceRetrievalState
        kwargs["context_schema"] = RetrievalReferenceContext
    return create_react_agent(
        model,
        tools=tools,
        prompt=prompt,
        state_schema=state_schema,
        **kwargs,
    )


def get_retrieval_agent():
    """Return the cached variant for the flag's value at this invocation."""
    return _build_retrieval_agent(follow_references_enabled())


def run_retrieval_agent(query: str, feedback: str = "", config=None) -> dict:
    """Run the ReAct loop for one query.

    Returns {"chunks": [...], "tools": [...]} — the accumulated chunks and the
    tool names the agent called (order preserved; used by the tool_selection
    eval). `feedback` (a re-retrieval pass, Phase 4) is appended to the request so
    the agent can adjust its search. `config` is the parent graph's RunnableConfig
    — forwarding it lets the tools' custom stream writes reach the parent's stream
    (so tool calls surface in the UI). We copy it and pin our own recursion_limit
    so the sub-loop stays bounded. Raises on failure — the wrapper decides whether
    to fail open.
    """
    request = query if not feedback else f"{query}\n\nRe-retrieval note: {feedback}"
    # Spread forwards the parent's metadata/tags/callbacks (so the sub-agent's
    # nested runs stay filterable in LangSmith); we pin our own recursion_limit
    # and run_name so this sub-loop reads as "retrieval_agent" rather than
    # inheriting whatever run name the parent config carried.
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

    # The tools emit tool_call events on THIS run's custom stream. A manually
    # invoked sub-agent's stream doesn't bubble to the parent graph, so when a
    # parent stream is active we stream the sub-agent and re-emit each custom
    # event through the parent writer; otherwise a plain invoke is enough.
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
            else:  # "values" — full state snapshots; keep the last
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
