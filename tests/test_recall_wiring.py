"""Graph-level wiring for the recall node (Semantic Memory read path, Phase 2).

Locks the fail-open contract:
  - flag on + a user_id + a seeded fact → the fact reaches the synthesiser as
    recalled Working Memory
  - no user_id, an empty store, or the flag off → clean no-op: the synthesiser
    sees no recalled_memory and the turn is unchanged
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from agent.graph import build_graph


def _config(thread_id: str, user_id: str | None = None) -> dict:
    return {"configurable": {"thread_id": thread_id, "user_id": user_id}}


class RecallWiringTests(unittest.TestCase):
    def _run(self, *, store, config, flag="on"):
        """Drive one legal-path turn, returning what the synthesiser saw as recalled_memory."""
        seen = {}

        def fake_synthesiser(state):
            seen["recalled_memory"] = state.get("recalled_memory", "")
            return {"draft_response": "Section 5 of the PDPA.", "citations": []}

        def fake_supervisor(state):
            return {"violations": [], "final_response": state["draft_response"]}

        with ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {"SEMANTIC_MEMORY_RECALL": flag}))
            stack.enter_context(patch("agent.graph.router_node", side_effect=lambda s: {"query_type": "topical"}))
            stack.enter_context(patch("agent.graph.contextualize_node", return_value={"standalone_query": ""}))
            stack.enter_context(patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}))
            stack.enter_context(patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser))
            stack.enter_context(patch("agent.graph.citation_validator_node", return_value={"violations": []}))
            stack.enter_context(patch("agent.graph.grounding_check_node", return_value={"violations": []}))
            stack.enter_context(patch("agent.graph.supervisor_node", side_effect=fake_supervisor))
            app = build_graph(MemorySaver(), store)
            app.invoke({"query": "What penalties apply under the PDPA?"}, config)

        return seen["recalled_memory"]

    def test_seeded_fact_reaches_synthesiser(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        recalled = self._run(store=store, config=_config("t1", "user-1"))

        self.assertIn("Prefers answers in Bahasa Malaysia", recalled)

    def test_no_user_id_is_noop(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        # No user_id in config → recall must not read the store at all.
        recalled = self._run(store=store, config=_config("t2", None))

        self.assertEqual(recalled, "")

    def test_empty_store_is_noop(self):
        recalled = self._run(store=InMemoryStore(), config=_config("t3", "user-1"))

        self.assertEqual(recalled, "")

    def test_flag_off_is_noop(self):
        store = InMemoryStore()
        store.put(("user-1", "semantic"), "pref-lang", {"text": "Prefers answers in Bahasa Malaysia"})

        # Even with a user_id and a seeded fact, recall stays dark when the flag is off.
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
