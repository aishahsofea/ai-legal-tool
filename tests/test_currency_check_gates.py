"""Phase 4 gate tests for #60 Track A (Act-currency check).

Turns the "field present only when non-empty" and per-turn reset acceptance
criteria into tests, mirroring test_commentary_gates.py's GraphResetTests and
SsePayloadEquivalenceTests for `commentary` -- same shape, new channel.
"""
import asyncio
import unittest
from unittest.mock import patch

from agent.graph import _start_turn
from agent.query_lifecycle import run_query, run_query_stream

CURRENCY_LABEL = {
    "act_number": "762",
    "label": "repealed",
    "detail_url": "https://example/act762-repealed.pdf",
    "as_of_date": "06/01/2018",
}


class GraphResetTests(unittest.TestCase):
    def test_start_turn_resets_currency_labels(self):
        state = {"currency_labels": [CURRENCY_LABEL], "query": "is the GST Act still in force?"}

        result = _start_turn(state)

        self.assertEqual(result["currency_labels"], [])


class SsePayloadEquivalenceTests(unittest.TestCase):
    """`currency_labels` is added to QueryResult / the SSE `response` event only
    when the turn produced at least one label. An empty or absent channel --
    always the case with CURRENCY_CHECK_ENABLED off, since the node then
    returns {} and never writes to it -- must leave both payloads identical to
    the pre-Phase-4 shape (acceptance criterion 1)."""

    def test_run_query_omits_currency_labels_key_when_empty(self):
        final_state = {
            "query_type": "topical",
            "final_response": "Section 1 of Example Act applies.",
            "draft_response": "Section 1 of Example Act applies.",
            "citations": [],
            "violations": [],
            "currency_labels": [],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertNotIn("currency_labels", result)

    def test_run_query_surfaces_currency_labels_when_present(self):
        final_state = {
            "query_type": "topical",
            "final_response": "Section 1 of Example Act applies.",
            "draft_response": "Section 1 of Example Act applies.",
            "citations": [],
            "violations": [],
            "currency_labels": [CURRENCY_LABEL],
        }

        with patch("agent.query_lifecycle.graph") as graph:
            graph.invoke.return_value = final_state
            result = run_query("What does the law say?", "t1")

        self.assertEqual(result["currency_labels"], [CURRENCY_LABEL])

    def test_stream_response_event_omits_currency_labels_key_when_empty(self):
        async def fake_astream(_input, _config, stream_mode=None):
            yield ("updates", {
                "supervisor": {
                    "final_response": "Section 1 of Example Act applies.",
                    "citations": [],
                    "violations": [],
                    "currency_labels": [],
                },
            })

        async def _collect():
            with patch("agent.query_lifecycle.graph") as graph:
                graph.astream = fake_astream
                return [event async for event in run_query_stream("What does the law say?", "t1")]

        events = asyncio.run(_collect())

        responses = [e for e in events if e["type"] == "response"]
        self.assertEqual(len(responses), 1)
        self.assertNotIn("currency_labels", responses[0])

    def test_stream_response_event_surfaces_currency_labels_when_present(self):
        async def fake_astream(_input, _config, stream_mode=None):
            yield ("updates", {
                "supervisor": {
                    "final_response": "Section 1 of Example Act applies.",
                    "citations": [],
                    "violations": [],
                    "currency_labels": [CURRENCY_LABEL],
                },
            })

        async def _collect():
            with patch("agent.query_lifecycle.graph") as graph:
                graph.astream = fake_astream
                return [event async for event in run_query_stream("What does the law say?", "t1")]

        events = asyncio.run(_collect())

        responses = [e for e in events if e["type"] == "response"]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["currency_labels"], [CURRENCY_LABEL])


if __name__ == "__main__":
    unittest.main()
