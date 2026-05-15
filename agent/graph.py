"""LangGraph agent graph for the Malaysian Legal Research Assistant.

This graph models the base one-pass flow:
router → retriever → synthesiser → supervisor

Retry policy lives in `agent.query_lifecycle` so the lifecycle module owns the
query loop and the graph stays a simple orchestration primitive.
"""
from langgraph.graph import END, StateGraph

from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.grounding_check import grounding_check_node
from agent.nodes.router import router_node
from agent.nodes.retriever import retriever_node
from agent.nodes.supervisor import ESCALATION_RESPONSE, supervisor_node
from agent.nodes.synthesiser import synthesiser_node
from agent.state import AgentState


def _route_from_router(state: AgentState) -> str:
    if state["query_type"] == "escalate":
        return END
    return "retriever"


def _escalate_node(state: AgentState) -> dict:
    return {"final_response": ESCALATION_RESPONSE}


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("router", router_node)
    g.add_node("escalate", _escalate_node)
    g.add_node("retriever", retriever_node)
    g.add_node("synthesiser", synthesiser_node)
    g.add_node("citation_validator", citation_validator_node)
    g.add_node("grounding_check", grounding_check_node)
    g.add_node("supervisor", supervisor_node)

    g.set_entry_point("router")
    g.add_conditional_edges("router", _route_from_router, {
        END: "escalate",
        "retriever": "retriever",
    })
    g.add_edge("escalate", END)
    g.add_edge("retriever", "synthesiser")
    g.add_edge("synthesiser", "citation_validator")
    g.add_edge("citation_validator", "grounding_check")
    g.add_edge("grounding_check", "supervisor")
    g.add_edge("supervisor", END)

    return g.compile()


# Module-level compiled graph — import this for use in tests if needed
graph = build_graph()
