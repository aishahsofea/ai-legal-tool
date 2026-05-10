"""
LangGraph agent graph for the Malaysian Legal Research Assistant.

Topology:
  router → retriever → synthesiser → supervisor
              ↑              ↑             |
              |         (retry ×1)    violations?
              |                           |
              └──────── synthesiser ←─────┘

Escalation path:
  router → END  (query contains specific-situation triggers)
"""
from langgraph.graph import END, StateGraph

from agent.nodes.router import router_node
from agent.nodes.retriever import retriever_node
from agent.nodes.synthesiser import synthesiser_node
from agent.nodes.supervisor import supervisor_node, ESCALATION_RESPONSE
from agent.state import AgentState

MAX_RETRIES = 1


def _route_from_router(state: AgentState) -> str:
    if state["query_type"] == "escalate":
        return END
    return "retriever"


def _route_from_supervisor(state: AgentState) -> str:
    if not state["violations"]:
        return END
    if state.get("retry_count", 0) >= MAX_RETRIES:
        return END
    return "synthesiser"


def _escalate_node(state: AgentState) -> dict:
    return {"final_response": ESCALATION_RESPONSE}


def _increment_retry(state: AgentState) -> dict:
    return {"retry_count": state.get("retry_count", 0) + 1}


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("router",      router_node)
    g.add_node("escalate",    _escalate_node)
    g.add_node("retriever",   retriever_node)
    g.add_node("synthesiser", synthesiser_node)
    g.add_node("supervisor",  supervisor_node)
    g.add_node("increment_retry", _increment_retry)

    g.set_entry_point("router")

    g.add_conditional_edges("router", _route_from_router, {
        END:         "escalate",
        "retriever": "retriever",
    })
    g.add_edge("escalate",  END)
    g.add_edge("retriever", "synthesiser")
    g.add_edge("synthesiser", "supervisor")

    g.add_conditional_edges("supervisor", _route_from_supervisor, {
        END:          END,
        "synthesiser": "increment_retry",
    })
    g.add_edge("increment_retry", "synthesiser")

    return g.compile()


# Module-level compiled graph — import this for use in the API and tests
graph = build_graph()
