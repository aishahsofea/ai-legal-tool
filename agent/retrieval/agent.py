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
from langchain.agents.middleware import ModelCallLimitMiddleware
from langgraph.errors import GraphRecursionError

from agent.llm_factory import make_llm, node_models
from agent.node_events import node_model_event
from agent.retrieval.reference_graph import (
    FollowOnceGuard,
    RetrievalReferenceContext,
    empty_reference_metrics,
    follow_references_enabled,
    should_follow_references,
)
from agent.retrieval.tools import (
    follow_references,
    lookup_section,
    search_commentary,
    search_statutes,
    web_commentary_enabled,
)
from agent.state import CommentaryNote

logger = logging.getLogger(__name__)

# The budget that actually bounds the loop. Measured on the eval corpus (#133):
# converging runs spend 4-5 model calls. One query never converged — it reformulated
# the same search past 15 calls, hunting a penalty section that corpus did not hold.
# 8 clears the observed ceiling and still cuts the runaway off.
# exit_behavior="end" is the point: the loop stops with the sections it has already
# retrieved still in hand, rather than raising and losing them.
MAX_MODEL_CALLS = int(os.getenv("RETRIEVAL_MAX_MODEL_CALLS", "8"))

# recursion_limit counts graph super-steps, not tool calls. ModelCallLimitMiddleware
# adds a before_model and an after_model node, so one round costs four super-steps
# (before, model, after, tools) — hence 4N. The extra two let the middleware see call
# N+1 coming and route to the end.
# Derived from MAX_MODEL_CALLS rather than set by hand: anything tighter and this
# backstop fires first, so the loop raises instead of returning. The old fixed 6
# allowed three model calls. Every run needing a third search round raised, and
# agentic_retriever_node's fail-open then threw away the sections already found
# (#133).
RECURSION_LIMIT = int(os.getenv("RETRIEVAL_RECURSION_LIMIT", str(4 * MAX_MODEL_CALLS + 2)))

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

_FOLLOW_REFERENCES_ADDENDUM = """

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

_COMMENTARY_ADDENDUM = """

When and only when `search_commentary` is available:
- It searches a small allowlist of trusted Malaysian legal-commentary
  publishers for background and explanatory material — practitioner
  briefings, firm client alerts, and similar secondary sources. It is never
  a source of statute text and never a substitute for `lookup_section` or
  `search_statutes`.
- Use it only when the question would benefit from practical or explanatory
  background beyond the bare text of a section — for example how firms
  advise clients on a provision, or what a recent amendment means in
  practice. Do not use it for an ordinary "what does section X say?"
  question, and do not use it as a routine first or only search.
- Always establish the statutory basis with `lookup_section` or
  `search_statutes` first, or alongside it. A question this tool cannot find
  statute sections for is not answered by commentary alone.
- You may call it more than once with a reformulated query if the first
  results look weak or off-topic, but do not keep searching indefinitely.
- Its results are background material, not evidence: never present a
  commentary note as if it were the text of the law, and never imply a
  provision says something only a commentary note claims."""


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
    # Declared unconditionally (not just on a commentary-enabled schema): an
    # undeclared channel breaks the graph, an unwritten one is harmless, and this
    # keeps the schema count at two rather than one per flag combination.
    commentary: Annotated[list[CommentaryNote], add]


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


@lru_cache(maxsize=4)
def _build_retrieval_agent(follow_enabled: bool, commentary_enabled: bool):
    """maxsize=4 covers all four flag combinations — two independent flags means
    two boolean params, and leaving the cache sized for one flag would silently
    bind the wrong tool list for whichever combination evicted first."""
    model = make_llm(os.getenv("RETRIEVAL_AGENT_MODEL", "gpt-4.1"), node="retrieval_agent")
    tools = [search_statutes, lookup_section]
    system_prompt = _SYSTEM
    kwargs = {}
    if follow_enabled:
        tools.append(follow_references)
        system_prompt += _FOLLOW_REFERENCES_ADDENDUM
        kwargs["context_schema"] = RetrievalReferenceContext
    if commentary_enabled:
        tools.append(search_commentary)
        system_prompt += _COMMENTARY_ADDENDUM
    # commentary is declared on the base RetrievalState, so both schemas carry
    # it regardless of commentary_enabled — no third/fourth schema class needed.
    state_schema = ReferenceRetrievalState if follow_enabled else RetrievalState
    return create_agent(
        model,
        tools=tools,
        system_prompt=system_prompt,
        state_schema=state_schema,
        # The prompt's "do not keep searching indefinitely" is advice the model is
        # free to ignore, and on a corpus missing the section it expects it does
        # ignore it. This is the same rule enforced where the model cannot argue.
        middleware=[ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS, exit_behavior="end")],
        **kwargs,
    )


def get_retrieval_agent():
    """Reads both flags per call, not at import, so flipping either dark launch
    takes effect without a restart."""
    return _build_retrieval_agent(follow_references_enabled(), web_commentary_enabled())


def run_retrieval_agent(query: str, feedback: str = "", config=None) -> dict:
    """Run the ReAct loop for one query.

    `feedback` comes from a re-retrieval pass so the agent can adjust its search.
    `config` is the parent graph's RunnableConfig; forwarding it is what lets the
    tools' stream writes reach the parent's stream.

    Raises on failure, leaving the fail-open decision to the caller in
    agent/nodes/retriever.py — except for a recursion-limit hit, which returns the
    partial state instead, since the sections already retrieved are worth more to
    that caller than an exception.
    """
    request = query if not feedback else f"{query}\n\nRe-retrieval note: {feedback}"
    # Spreading keeps the parent's metadata/tags/callbacks so nested runs stay
    # filterable in LangSmith; recursion_limit and run_name are pinned so the
    # sub-loop stays bounded and doesn't inherit the parent's run name.
    invoke_config = {**(config or {}), "recursion_limit": RECURSION_LIMIT, "run_name": "retrieval_agent"}
    follow_enabled = follow_references_enabled()
    commentary_enabled = web_commentary_enabled()
    agent = _build_retrieval_agent(follow_enabled, commentary_enabled)
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
    # graph, so when a parent stream is active we re-emit each event through the
    # parent's writer.
    parent_writer = None
    try:
        parent_writer = get_stream_writer()
    except Exception:
        parent_writer = None

    # Streamed even with no parent writer to re-emit for: invoke() returns nothing
    # at all when a run trips the recursion backstop, and the sections found before
    # that point are exactly what the caller's fail-open needs.
    final_state: dict = {}
    stream_kwargs: dict = {
        "stream_mode": ["values"] if parent_writer is None else ["custom", "values"],
    }
    if context is not None:
        stream_kwargs["context"] = context

    # One event for the whole ReAct loop, not per internal call: the panel's
    # question is whether the retrieval agent ran and on what, and the individual
    # tool calls already have their own rows. node_models() rather than the env
    # var, so this reports what _build_retrieval_agent actually bound.
    with node_model_event("retrieval_agent", node_models().get("retrieval_agent", "")):
        try:
            for mode, chunk in agent.stream(agent_input, invoke_config, **stream_kwargs):
                if mode == "custom":
                    parent_writer(chunk)
                else:  # "values" emits full snapshots, so the last one is final
                    final_state = chunk
        except GraphRecursionError:
            # Swallowed, not re-raised: MAX_MODEL_CALLS ends the loop first, so
            # getting here means RETRIEVAL_RECURSION_LIMIT was set below the call
            # budget. Partial evidence beats none, and the node's fail-open still
            # reaches the deterministic path if the partial state is empty.
            logger.warning(
                "retrieval agent hit RETRIEVAL_RECURSION_LIMIT=%s; keeping %d partial chunk(s)",
                RECURSION_LIMIT,
                len(final_state.get("retrieved_chunks", [])),
            )

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
    if commentary_enabled:
        result["commentary"] = final_state.get("commentary", [])
    return result
