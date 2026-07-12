"""LangSmith observability: per-turn quality-gate feedback scores.

The agent computes rich quality signals every turn (violations, evidence gaps,
retries, whether the safe fallback was delivered) but they live only in
`AgentState`. This module posts them to LangSmith as run feedback so they become
filterable/chartable — turning the trace dashboard into a quality dashboard.

Two halves, deliberately split:
  * `build_feedback` is a PURE function (state -> score dict). No network, no
    LangSmith import — fully unit-testable.
  * `emit_feedback` does the I/O: it is fail-open (never raises into the caller)
    and a no-op when tracing is disabled, matching the codebase's ethos (recall,
    memory, agentic retrieval all fail open).

Feedback is posted with `trace_id` so LangSmith routes it through the background
tracing batch (a non-blocking enqueue) rather than a synchronous POST that could
race the run's own upload.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from agent.query_policy import FINAL_FAILURE_RESPONSE, delivered_response

logger = logging.getLogger(__name__)


def build_feedback(state: dict[str, Any]) -> dict[str, Any]:
    """Map a finished turn's state to a {feedback_key: value} dict.

    Pure and side-effect free. Numeric values become feedback `score`s; the lone
    string value (`query_type`) is posted as a categorical `value` (see
    `emit_feedback`). All keys derive from existing AgentState fields; there is no
    groundedness float in state today (the per-claim support labels in
    grounding_check are not persisted), so `passed` / `num_evidence_violations`
    are the honest proxies. A richer continuous score is a future enhancement.
    """
    violations = state.get("violations") or []
    evidence_violations = state.get("evidence_violations") or []
    citations = state.get("citations") or []
    query_type = state.get("query_type", "")
    fallback = delivered_response(state) == FINAL_FAILURE_RESPONSE

    return {
        "passed": 0.0 if violations else 1.0,
        "num_violations": float(len(violations)),
        "num_evidence_violations": float(len(evidence_violations)),
        "retry_count": float(state.get("retry_count", 0)),
        "num_citations": float(len(citations)),
        "fallback_delivered": 1.0 if fallback else 0.0,
        "escalated": 1.0 if query_type == "escalate" else 0.0,
        # Categorical — posted as a feedback `value`, not a `score`.
        "query_type": query_type,
    }


# Numeric keys go out as `score=`; this one goes out as `value=`.
_CATEGORICAL_KEYS = {"query_type"}


@lru_cache(maxsize=1)
def _client():
    from langsmith import Client
    return Client()


def _tracing_enabled() -> bool:
    try:
        from langsmith.utils import tracing_is_enabled
        return tracing_is_enabled()
    except Exception:
        return False


def emit_feedback(run_id, state: dict[str, Any]) -> None:
    """Post the turn's quality scores to the LangSmith run. Fail-open.

    No-op when tracing is disabled or `run_id` is falsy. Any client/HTTP error is
    swallowed (logged at debug) — feedback must never break a user response.
    `run_id` is a root run, so `run_id == trace_id`; passing `trace_id` routes the
    feedback through the background batch (non-blocking).
    """
    if not run_id or not _tracing_enabled():
        return
    try:
        client = _client()
        for key, value in build_feedback(state).items():
            if key in _CATEGORICAL_KEYS:
                client.create_feedback(run_id, key=key, value=value, trace_id=run_id)
            else:
                client.create_feedback(run_id, key=key, score=value, trace_id=run_id)
    except Exception:  # pragma: no cover - defensive, fail-open
        logger.debug("LangSmith feedback emission failed", exc_info=True)


def root_run_id(collector) -> Any | None:
    """Pull the root run id from a RunCollectorCallbackHandler, or None.

    `.traced_runs` only ever holds root runs (child runs are not persisted to it),
    so there is normally exactly one; the parent_run_id guard is belt-and-braces.
    """
    if collector is None:
        return None
    for run in getattr(collector, "traced_runs", []):
        if getattr(run, "parent_run_id", None) is None:
            return run.id
    return None
