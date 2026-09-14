"""The `node` SSE event: one row per model call for the PROCESS panel (#61).

Covers the emitter (agent/node_events.py) and the passthrough in
run_query_stream. Node wiring — that a short-circuiting node stays silent — is
asserted against the real router, since that is the case the panel gets wrong.
"""
import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from agent.node_events import node_model_event
from agent.query_lifecycle import run_query_stream

_FINAL = {"supervisor": {"final_response": "Section 5 applies.", "citations": [], "violations": []}}


async def _collect(query, updates):
    async def fake_astream(_input, _config, stream_mode=None):
        for update in updates:
            yield update if isinstance(update, tuple) else ("updates", update)

    with patch("agent.query_lifecycle.graph") as graph:
        graph.astream = fake_astream
        return [event async for event in run_query_stream(query, "t1")]


def _run(query, updates):
    return asyncio.run(_collect(query, updates))


class EmitterTests(unittest.TestCase):
    def test_emits_node_model_and_duration(self):
        writer = MagicMock()
        with patch("agent.node_events.get_stream_writer", return_value=writer):
            with node_model_event("synthesiser", "nemotron-super"):
                pass
        payload = writer.call_args[0][0]["node_event"]
        self.assertEqual(payload["node"], "synthesiser")
        self.assertEqual(payload["model"], "nemotron-super")
        self.assertIsInstance(payload["duration_ms"], int)

    def test_nothing_emitted_when_call_raises(self):
        """A failed call is the error event's business; the panel says what ran."""
        writer = MagicMock()
        with patch("agent.node_events.get_stream_writer", return_value=writer):
            with self.assertRaises(ValueError):
                with node_model_event("synthesiser", "nemotron-super"):
                    raise ValueError("provider down")
        writer.assert_not_called()

    def test_silent_without_an_active_stream(self):
        """A plain .invoke() from a test or eval has no writer. Not an error."""
        with patch("agent.node_events.get_stream_writer", side_effect=RuntimeError("no stream")):
            with node_model_event("router", "gpt-4.1"):
                pass

    def test_payload_carries_no_prompt_or_content(self):
        writer = MagicMock()
        with patch("agent.node_events.get_stream_writer", return_value=writer):
            with node_model_event("router", "gpt-4.1"):
                pass
        self.assertEqual(set(writer.call_args[0][0]["node_event"]), {"node", "model", "duration_ms"})


class StreamPassthroughTests(unittest.TestCase):
    def test_node_event_becomes_node_sse_event(self):
        updates = [
            ("custom", {"node_event": {"node": "router", "model": "gpt-4.1", "duration_ms": 412}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("q", updates)
        rows = [e for e in events if e["type"] == "node"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "router")
        self.assertEqual(rows[0]["model"], "gpt-4.1")
        self.assertEqual(rows[0]["duration_ms"], 412)

    def test_tool_calls_still_pass_through(self):
        """Regression guard: the node branch must not swallow tool_call chunks."""
        updates = [
            ("custom", {"tool_call": {"name": "search_statutes", "summary": "Searching"}}),
            ("custom", {"node_event": {"node": "synthesiser", "model": "m", "duration_ms": 1}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("q", updates)
        self.assertEqual(len([e for e in events if e["type"] == "tool_call"]), 1)
        self.assertEqual(len([e for e in events if e["type"] == "node"]), 1)

    def test_events_arrive_in_execution_order(self):
        updates = [
            ("custom", {"node_event": {"node": "router", "model": "m1", "duration_ms": 1}}),
            ("custom", {"node_event": {"node": "synthesiser", "model": "m2", "duration_ms": 2}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        rows = [e["name"] for e in _run("q", updates) if e["type"] == "node"]
        self.assertEqual(rows, ["router", "synthesiser"])

    def test_retry_emits_a_second_synthesiser_row(self):
        updates = [
            ("custom", {"node_event": {"node": "synthesiser", "model": "m", "duration_ms": 10}}),
            ("custom", {"node_event": {"node": "synthesiser", "model": "m", "duration_ms": 12}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        rows = [e for e in _run("q", updates) if e["type"] == "node"]
        self.assertEqual(len(rows), 2)

    def test_unknown_custom_chunk_is_ignored(self):
        updates = [("custom", {"something_else": {"x": 1}}), {"supervisor": _FINAL["supervisor"]}]
        events = _run("q", updates)
        self.assertEqual([e for e in events if e["type"] == "node"], [])

    def test_client_ignoring_node_events_sees_todays_stream(self):
        """The event is additive: drop it and the turn is unchanged."""
        plain = [{"supervisor": _FINAL["supervisor"]}]
        with_rows = [
            ("custom", {"node_event": {"node": "router", "model": "m", "duration_ms": 1}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        before = _run("q", plain)
        after = [e for e in _run("q", with_rows) if e["type"] != "node"]
        self.assertEqual(before, after)


class ShortCircuitTests(unittest.TestCase):
    def test_escalation_shortcut_emits_no_row(self):
        """router_node returns before its model call on an escalation keyword."""
        from agent.nodes import router
        writer = MagicMock()
        with patch("agent.node_events.get_stream_writer", return_value=writer):
            out = router.router_node({"query": "am i liable under section 300?", "history": []})
        self.assertEqual(out["query_type"], "escalate")
        writer.assert_not_called()

    def test_contextualize_first_turn_emits_no_row(self):
        """No history means no LLM call, so no row."""
        from agent.nodes import contextualize
        writer = MagicMock()
        with patch("agent.node_events.get_stream_writer", return_value=writer):
            contextualize.contextualize_node({"query": "hello", "history": []})
        writer.assert_not_called()

    def test_router_emits_one_row_on_the_model_path(self):
        from agent.nodes import router
        writer = MagicMock()
        with patch.object(router, "_structured_llm") as llm, \
             patch("agent.node_events.get_stream_writer", return_value=writer):
            llm.invoke.return_value = MagicMock(
                query_type="statute_lookup", response_language="en", clarifying_question="",
            )
            router.router_node({"query": "what does section 5 say?", "history": []})
        self.assertEqual(writer.call_count, 1)
        self.assertEqual(writer.call_args[0][0]["node_event"]["node"], "router")


if __name__ == "__main__":
    unittest.main()
