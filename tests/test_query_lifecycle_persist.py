import asyncio
from unittest.mock import patch

from agent.query_lifecycle import run_query_stream

_CITATION = {"act_number": "136", "section_number": "5", "receipt": {"document_id": "act-136"}}
_FINAL = {"supervisor": {
    "final_response": "Section 5 applies.",
    "citations": [_CITATION], "violations": [], "query_type": "topical",
    "currency_labels": [{"label": "in_force"}],
}}


def _drive(updates, *, query="What is section 5?", resume=None, persist=True, append=None):
    calls = []

    def record(*args):
        calls.append(args)
        if append is not None:
            append()

    async def fake_astream(_input, _config, stream_mode=None):
        for update in updates:
            yield ("updates", update)

    async def collect():
        with patch("agent.query_lifecycle.graph") as graph, \
             patch("agent.query_lifecycle.schedule_extraction"), \
             patch("agent.query_lifecycle.schedule_pruning"), \
             patch("agent.query_lifecycle.threads_store.append_turn", side_effect=record):
            graph.astream = fake_astream
            return [e async for e in run_query_stream(query, "t1", "alice", resume=resume, persist=persist)]

    return asyncio.run(collect()), calls


def test_completed_turn_is_stored_with_its_citations():
    events, calls = _drive([_FINAL])
    assert events[-1]["type"] == "response"
    assert calls == [("t1", "What is section 5?", "Section 5 applies.", [_CITATION], None, [{"label": "in_force"}])]


def test_resumed_turn_stores_the_merged_query():
    merged = {"clarify": {"query": "What is section 5? (clarified: Contracts Act 1950)"}}
    _events, calls = _drive([merged, _FINAL], query=None, resume="Contracts Act 1950")
    assert calls[0][1] == "What is section 5? (clarified: Contracts Act 1950)"


def test_paused_turn_is_not_stored():
    events, calls = _drive([{"__interrupt__": ({"question": "Which Act?"},)}])
    assert events[-1]["type"] == "interrupt"
    assert calls == []


def test_without_persist_nothing_is_stored():
    _events, calls = _drive([_FINAL], persist=False)
    assert calls == []


def test_store_failure_does_not_break_the_answer():
    def fail():
        raise RuntimeError("db down")

    events, calls = _drive([_FINAL], append=fail)
    assert len(calls) == 1
    assert events[-1]["type"] == "response"
