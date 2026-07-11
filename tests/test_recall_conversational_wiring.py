"""Graph-level wiring for recall on the conversational short-circuit (ADR 0010).

Conversational turns now pass through a recall step before the conversational node,
so remembered practitioner preferences reach small talk too — the same fail-open
contract locked for the legal path in test_recall_wiring.py, just a different
consumer. The store write path is unchanged: conversational turns still don't extract.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import build_graph


def _config(thread_id: str, user_id: str | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id, "user_id": user_id}}


class RecallConversationalWiringTests(unittest.TestCase):
    def _run(self, *, store, config, flag="on"):
        """Drive one conversational-path turn, returning what the conversational node saw."""
        seen = {}

        def fake_conversational(state):
            seen["recalled_memory"] = state.get("recalled_memory", "")
            return {"final_response": "Hi there!", "draft_response": "Hi there!"}

        with ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {"SEMANTIC_MEMORY_RECALL": flag}))
            stack.enter_context(patch(
                "agent.graph.router_node",
                side_effect=lambda s: {"query_type": "conversational", "response_language": "en"},
            ))
            stack.enter_context(patch("agent.graph.conversational_node", side_effect=fake_conversational))
            app = build_graph(MemorySaver(), store)
            app.invoke({"query": "hey there"}, config)

        return seen["recalled_memory"]

    def test_seeded_fact_reaches_conversational(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        recalled = self._run(store=store, config=_config("t1", "user-1"))

        self.assertIn("Prefers answers in Bahasa Malaysia", recalled)

    def test_no_user_id_is_noop(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        recalled = self._run(store=store, config=_config("t2", None))

        self.assertEqual(recalled, "")

    def test_empty_store_is_noop(self):
        recalled = self._run(store=InMemoryStore(), config=_config("t3", "user-1"))

        self.assertEqual(recalled, "")

    def test_flag_off_is_noop(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        recalled = self._run(store=store, config=_config("t4", "user-1"), flag="off")

        self.assertEqual(recalled, "")

    def test_facts_only_scoped_to_this_user(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref", {"text": "user-1 likes short answers"})
        store.put(("user-2", "semantic"), "pref", {"text": "user-2 likes long answers"})

        recalled = self._run(store=store, config=_config("t5", "user-1"))

        self.assertIn("user-1 likes short answers", recalled)
        self.assertNotIn("user-2", recalled)


if __name__ == "__main__":
    unittest.main()
