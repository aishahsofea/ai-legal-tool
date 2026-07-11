"""run_query_stream surfaces a "Resolving follow-up..." status ONLY when the
contextualize node actually rewrote the query — never the rewritten text itself,
and never on a first turn / fail-open (empty standalone_query)."""
import unittest
from unittest.mock import patch

from agent.query_lifecycle import run_query_stream


async def _collect(query, updates):
    # Production streams stream_mode=["updates", "custom"], so each item is a
    # (mode, chunk) tuple. Plain dicts here are treated as "updates" chunks.
    async def fake_astream(_input, _config, stream_mode=None):
        for update in updates:
            yield update if isinstance(update, tuple) else ("updates", update)

    with patch("agent.query_lifecycle.graph") as graph:
        graph.astream = fake_astream
        return [event async for event in run_query_stream(query, "t1")]


def _run(query, updates):
    import asyncio
    return asyncio.run(_collect(query, updates))


_FINAL = {
    "supervisor": {"final_response": "Section 5 of the PDPA applies.", "citations": [], "violations": []},
}


class FollowUpStatusTests(unittest.TestCase):
    def test_status_emitted_when_query_was_rewritten(self):
        updates = [
            {"contextualize": {"standalone_query": "Does the PDPA apply to criminal cases?"}},
            _FINAL["supervisor"] and {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("what about criminal cases?", updates)
        statuses = [e["message"] for e in events if e["type"] == "status"]
        self.assertIn("Resolving follow-up...", statuses)
        # The rewritten text is never surfaced to the user.
        self.assertNotIn(
            "Does the PDPA apply to criminal cases?",
            " ".join(e.get("message", "") for e in events),
        )

    def test_no_status_when_standalone_empty(self):
        updates = [
            {"contextualize": {"standalone_query": ""}},
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("What does Section 5 of the PDPA say?", updates)
        statuses = [e["message"] for e in events if e["type"] == "status"]
        self.assertNotIn("Resolving follow-up...", statuses)

    def test_no_status_when_standalone_equals_raw_query(self):
        # Already self-contained: rewrite == raw, so no follow-up was resolved.
        q = "What does Section 5 of the PDPA say?"
        updates = [
            {"contextualize": {"standalone_query": q}},
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run(q, updates)
        statuses = [e["message"] for e in events if e["type"] == "status"]
        self.assertNotIn("Resolving follow-up...", statuses)

    def test_custom_tool_call_chunk_becomes_tool_call_event(self):
        # The retrieval agent's tools emit custom chunks; run_query_stream turns
        # each into a tool_call SSE event with name + summary.
        updates = [
            ("custom", {"tool_call": {"name": "search_statutes", "summary": "Searching statutes: “x”"}}),
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("which laws cover data privacy?", updates)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "search_statutes")
        self.assertIn("Searching statutes", tool_calls[0]["summary"])

    def test_noop_node_update_none_does_not_crash(self):
        # A node that makes no state change (e.g. recall no-oping on an empty store)
        # surfaces as {node: None} in the updates stream; the stream must tolerate it.
        updates = [
            {"recall": None},
            {"supervisor": _FINAL["supervisor"]},
        ]
        events = _run("What does Section 5 of the PDPA say?", updates)
        responses = [e for e in events if e["type"] == "response"]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["content"], "Section 5 of the PDPA applies.")


if __name__ == "__main__":
    unittest.main()
