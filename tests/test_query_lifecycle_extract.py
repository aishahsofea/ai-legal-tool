"""run_query_stream fires the write path only on the legal path, and only after the
response event — never on conversational / escalate turns."""
import asyncio
import unittest
from unittest.mock import patch

from agent.query_lifecycle import run_query_stream


def _drive(query, updates, user_id="user-1"):
    """Run one streamed turn over canned graph updates, capturing schedule_extraction calls."""
    calls = []

    async def fake_astream(_input, _config, stream_mode=None):
        for update in updates:
            yield update

    async def collect():
        with patch("agent.query_lifecycle.graph") as graph, \
             patch("agent.query_lifecycle.schedule_extraction",
                   side_effect=lambda *a, **k: calls.append(a)):
            graph.astream = fake_astream
            graph.store = "STORE"
            return [e async for e in run_query_stream(query, "t1", user_id)]

    events = asyncio.run(collect())
    return events, calls


_LEGAL_FINAL = {"supervisor": {
    "final_response": "Section 5 of the PDPA applies.",
    "citations": [], "violations": [], "query_type": "topical",
}}


class ExtractLifecycleTests(unittest.TestCase):
    def test_legal_turn_schedules_extraction_after_response(self):
        events, calls = _drive("What penalties apply under the PDPA?", [_LEGAL_FINAL])

        self.assertEqual(len(calls), 1)
        store, user_id, sent_query, sent_response = calls[0]
        self.assertEqual((store, user_id), ("STORE", "user-1"))
        self.assertEqual(sent_query, "What penalties apply under the PDPA?")
        # Scheduled strictly after the response, which is the last emitted event.
        self.assertEqual(events[-1]["type"], "response")

    def test_conversational_turn_does_not_extract(self):
        updates = [{"conversational": {
            "final_response": "Hi! How can I help with Malaysian legal research?",
            "citations": [], "query_type": "conversational",
        }}]
        _events, calls = _drive("hello there", updates)
        self.assertEqual(calls, [])

    def test_escalate_turn_does_not_extract(self):
        updates = [{"escalate": {
            "final_response": "I'm escalating this to a human lawyer.",
            "query_type": "escalate",
        }}]
        _events, calls = _drive("should I plead guilty?", updates)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
