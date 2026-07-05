"""Semantic Memory write path — extraction gating, fail-open, and the write→read
round-trip with recall. The LangMem manager is always mocked: this locks the wiring
contract, not the LLM's extraction quality (that belongs in an eval)."""
import asyncio
import os
import unittest
from unittest.mock import patch

from langgraph.store.memory import InMemoryStore

from agent.memory.extractor import _EXTRACTION_INSTRUCTIONS, extract_memory
from agent.nodes.recall import recall_node


class _FakeManager:
    """Records ainvoke calls; optionally writes a fact or raises."""

    def __init__(self, *, put=None, raises=False):
        self.calls = []
        self._put = put
        self._raises = raises

    async def ainvoke(self, input, config=None):
        self.calls.append((input, config))
        if self._raises:
            raise RuntimeError("boom")
        if self._put:
            self._put(config)


def _extract(store, user_id, *, flag="on", query="What penalties apply under the PDPA?",
             response="Section 5 of the PDPA applies.", manager=None):
    manager = manager or _FakeManager()
    with patch.dict(os.environ, {"SEMANTIC_MEMORY_EXTRACT": flag}), \
         patch("agent.memory.extractor._manager", return_value=manager):
        asyncio.run(extract_memory(store, user_id, query, response))
    return manager


class ExtractGatingTests(unittest.TestCase):
    def test_legal_turn_invokes_manager_with_scoped_config(self):
        manager = _extract(InMemoryStore(), "user-1")

        self.assertEqual(len(manager.calls), 1)
        sent_input, sent_config = manager.calls[0]
        self.assertEqual(sent_input["messages"], [
            {"role": "user", "content": "What penalties apply under the PDPA?"},
            {"role": "assistant", "content": "Section 5 of the PDPA applies."},
        ])
        # config user_id is what the namespace template resolves to (user_id, "semantic").
        self.assertEqual(sent_config, {"configurable": {"user_id": "user-1"}})

    def test_flag_off_is_noop(self):
        manager = _extract(InMemoryStore(), "user-1", flag="off")
        self.assertEqual(manager.calls, [])

    def test_no_user_id_is_noop(self):
        manager = _extract(InMemoryStore(), None)
        self.assertEqual(manager.calls, [])

    def test_anonymous_user_id_is_noop(self):
        manager = _extract(InMemoryStore(), "anonymous")
        self.assertEqual(manager.calls, [])

    def test_no_store_is_noop(self):
        manager = _extract(None, "user-1")
        self.assertEqual(manager.calls, [])

    def test_empty_response_is_noop(self):
        manager = _extract(InMemoryStore(), "user-1", response="   ")
        self.assertEqual(manager.calls, [])

    def test_extraction_error_is_swallowed(self):
        # Fail-open: a raising manager must not propagate out of extract_memory.
        manager = _extract(InMemoryStore(), "user-1", manager=_FakeManager(raises=True))
        self.assertEqual(len(manager.calls), 1)

    def test_instructions_exclude_client_and_matter_facts(self):
        # Guard the exclusion language so it can't be silently deleted. Behavioural
        # privacy ("a client fact stores nothing") needs a real LLM and lives in an eval.
        lowered = _EXTRACTION_INSTRUCTIONS.lower()
        self.assertIn("client", lowered)
        self.assertIn("matter", lowered)
        self.assertIn("privilege", lowered)

    def test_instructions_capture_response_format_preferences(self):
        # Guard that the prompt still steers toward capturing answer-format directives
        # (brevity/bullets), which recall surfaces. Behavioural capture lives in an eval.
        lowered = _EXTRACTION_INSTRUCTIONS.lower()
        self.assertIn("format", lowered)
        self.assertIn("brief", lowered)
        self.assertIn("bullet", lowered)


class WriteReadRoundTripTests(unittest.TestCase):
    """Write path and recall agree on namespace and value shape."""

    def test_written_profile_is_recalled_and_rendered(self):
        store = InMemoryStore()

        def put(config):
            user_id = config["configurable"]["user_id"]
            # LangMem's stored shape: {"kind": ..., "content": {<fields>}}.
            store.put((user_id, "semantic"), "profile", {
                "kind": "PractitionerProfile",
                "content": {"response_language": "bm", "practice_areas": ["employment"]},
            })

        _extract(store, "user-1", manager=_FakeManager(put=put))

        with patch.dict(os.environ, {"SEMANTIC_MEMORY_RECALL": "on"}):
            recalled = recall_node(
                {"query": "unfair dismissal"},
                {"configurable": {"user_id": "user-1"}},
                store=store,
            )["recalled_memory"]

        self.assertIn("response language: bm", recalled)
        self.assertIn("practice areas: employment", recalled)

    def test_recurring_topic_is_recalled(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "topic", {
            "kind": "RecurringTopic",
            "content": {"topic": "unfair dismissal remedies"},
        })

        with patch.dict(os.environ, {"SEMANTIC_MEMORY_RECALL": "on"}):
            recalled = recall_node(
                {"query": "dismissal"},
                {"configurable": {"user_id": "user-1"}},
                store=store,
            )["recalled_memory"]

        self.assertIn("topic: unfair dismissal remedies", recalled)


if __name__ == "__main__":
    unittest.main()
