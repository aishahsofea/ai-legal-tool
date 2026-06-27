import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph
from agent.nodes import conversational
from agent.query_policy import FINAL_FAILURE_RESPONSE

_CONFIG = {"configurable": {"thread_id": "t1"}}


class GraphConversationalTests(unittest.TestCase):
    def test_conversational_turn_bypasses_retriever_and_delivers_warm_reply(self):
        warm = "Hi Shameel! I research Malaysian legislation — what would you like to look up?"

        def fake_router(state):
            return {"query_type": "conversational", "response_language": "en"}

        with patch("agent.graph.router_node", side_effect=fake_router), \
             patch("agent.graph.retriever_node") as mock_retriever, \
             patch.object(conversational, "_llm") as mock_llm:
            mock_llm.invoke.return_value = Mock(content=warm)
            app = build_graph(MemorySaver())
            result = app.invoke({"query": "hi my name is shameel"}, _CONFIG)

        # Routed router → conversational → record_turn: retriever never ran.
        mock_retriever.assert_not_called()
        # Delivered text is the warm reply, NOT the legal dead-end fallback.
        self.assertEqual(result["final_response"], warm)
        self.assertNotEqual(result["final_response"], FINAL_FAILURE_RESPONSE)
        self.assertEqual(result["citations"], [])
        # Turn appended to history (no disclaimer to strip).
        assistant_turns = [m for m in result["history"] if m["role"] == "assistant"]
        self.assertEqual(assistant_turns[-1]["content"], warm)


if __name__ == "__main__":
    unittest.main()
