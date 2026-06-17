import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver

from agent.graph import build_graph
from agent.query_policy import MAX_RETRIES

_CONFIG = {"configurable": {"thread_id": "t1"}}


class GraphRetryTests(unittest.TestCase):
    def test_graph_retries_synthesiser_when_supervisor_reports_violations(self):
        calls = {"synthesiser": 0}

        def fake_router(state):
            return {"query_type": "topical"}

        def fake_retriever(state):
            return {"retrieved_chunks": []}

        def fake_synthesiser(state):
            calls["synthesiser"] += 1
            if state.get("retry_count", 0):
                return {"draft_response": "Section 1 of Example Act applies.", "citations": []}
            return {"draft_response": "You should do X.", "citations": []}

        def fake_supervisor(state):
            if "You should" in state["draft_response"]:
                return {"violations": ["advice"], "final_response": state["draft_response"]}
            return {"violations": [], "final_response": state["draft_response"]}

        with patch("agent.graph.router_node", side_effect=fake_router), \
             patch("agent.graph.retriever_node", side_effect=fake_retriever), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser), \
             patch("agent.graph.citation_validator_node", return_value={"violations": []}), \
             patch("agent.graph.grounding_check_node", return_value={"violations": []}), \
             patch("agent.graph.supervisor_node", side_effect=fake_supervisor):
            app = build_graph(MemorySaver())
            result = app.invoke(_initial_state(), _CONFIG)

        self.assertEqual(calls["synthesiser"], 2)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["violations"], [])
        self.assertEqual(result["final_response"], "Section 1 of Example Act applies.")

    def test_graph_stops_after_max_retries(self):
        calls = {"synthesiser": 0}

        def fake_router(state):
            return {"query_type": "topical"}

        def fake_synthesiser(state):
            calls["synthesiser"] += 1
            return {"draft_response": "You should do X.", "citations": []}

        with patch("agent.graph.router_node", side_effect=fake_router), \
             patch("agent.graph.retriever_node", return_value={"retrieved_chunks": []}), \
             patch("agent.graph.synthesiser_node", side_effect=fake_synthesiser), \
             patch("agent.graph.citation_validator_node", return_value={"violations": []}), \
             patch("agent.graph.grounding_check_node", return_value={"violations": []}), \
             patch("agent.graph.supervisor_node", return_value={"violations": ["advice"], "final_response": "You should do X."}):
            app = build_graph(MemorySaver())
            result = app.invoke(_initial_state(), _CONFIG)

        self.assertEqual(calls["synthesiser"], MAX_RETRIES + 1)
        self.assertEqual(result["retry_count"], MAX_RETRIES)
        self.assertEqual(result["violations"], ["advice"])


def _initial_state():
    # start_turn now seeds all per-query fields; the turn input is just the query.
    return {"query": "What does the law say?"}


if __name__ == "__main__":
    unittest.main()
