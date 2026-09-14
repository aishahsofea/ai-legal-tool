"""Per-node model rows for the UI's PROCESS panel (issue #61).

A mixed-provider turn raises two questions the stream could not answer: which
model wrote this, and did the expensive one actually run. This emits one `node`
event per model call so the panel can say so without anyone opening LangSmith.

Payload is deliberately thin — node name, model name, milliseconds. No prompt
text, no user content, no token counts. The panel is a debugging surface, not a
claim about quality.
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from langgraph.config import get_stream_writer


@contextmanager
def node_model_event(node: str, model: str):
    """Emit one `node` event once the wrapped model call returns.

    Wrap the call itself, never the whole node: a router that short-circuits on an
    escalation keyword never reaches its model, and a row claiming it ran would be
    a lie. Nothing is emitted when the call raises either — the panel says what
    ran, and a failure is the error event's business.

    Silent when no stream is active, matching agent/retrieval/tools.py::_emit. A
    plain .invoke() from a test or an eval has no writer, and that is not an error.
    """
    started = time.perf_counter()
    yield
    duration_ms = round((time.perf_counter() - started) * 1000)
    try:
        get_stream_writer()(
            {"node_event": {"node": node, "model": model, "duration_ms": duration_ms}}
        )
    except Exception:
        pass
