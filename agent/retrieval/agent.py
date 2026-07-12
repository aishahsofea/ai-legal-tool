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

from langgraph.config import get_stream_writer
from langgraph.graph.message import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState as _ReactAgentState
from typing_extensions import Annotated

from agent.llm_factory import make_llm
from agent.retrieval.tools import lookup_section, search_statutes

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


def _dedupe_chunks(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
    """Reducer for the retrieved_chunks channel: accumulate across tool calls,
    keeping the first-seen chunk per (act_number, section_number, language)."""
    merged: list[dict] = []
    seen: set[tuple] = set()
    for chunk in (left or []) + (right or []):
        key = (
            str(chunk.get("act_number", "")),
            str(chunk.get("section_number", "")).upper(),
            str(chunk.get("language", "")),
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


@lru_cache(maxsize=1)
def get_retrieval_agent():
    """Compile the retrieval agent once (lazily, so import is cheap and offline)."""
    model = make_llm(os.getenv("RETRIEVAL_AGENT_MODEL", "gpt-4.1"))
    return create_react_agent(
        model,
        tools=[search_statutes, lookup_section],
        prompt=_SYSTEM,
        state_schema=RetrievalState,
    )


def _tool_names(messages: list) -> list[str]:
    """Names of tools the agent called, in order, from its message trace."""
    names: list[str] = []
    for m in messages or []:
        for tc in getattr(m, "tool_calls", None) or []:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            if name:
                names.append(name)
    return names


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
    agent = get_retrieval_agent()
    agent_input = {"messages": [{"role": "user", "content": request}]}

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
        final_state = agent.invoke(agent_input, invoke_config)
    else:
        final_state = {}
        for mode, chunk in agent.stream(agent_input, invoke_config, stream_mode=["custom", "values"]):
            if mode == "custom":
                parent_writer(chunk)
            else:  # "values" — full state snapshots; keep the last
                final_state = chunk

    return {
        "chunks": final_state.get("retrieved_chunks", []),
        "tools": _tool_names(final_state.get("messages", [])),
    }
