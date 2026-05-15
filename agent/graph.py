"""LangGraph agent graph for the Malaysian Legal Research Assistant.

The graph owns the full query lifecycle, including bounded retries:
router → retriever → synthesiser → citation_validator → grounding_check → supervisor
                                      ↑                               ↓
                                      └──── retry when violations ────┘
"""
from langgraph.graph import END, StateGraph

from agent.nodes.citation_validator import citation_validator_node
from agent.nodes.grounding_check import grounding_check_node
from agent.nodes.router import router_node
from agent.nodes.retriever import retriever_node
from agent.nodes.supervisor import ESCALATION_RESPONSE, supervisor_node
from agent.nodes.synthesiser import synthesiser_node
from agent.query_policy import MAX_RETRIES
from agent.state import AgentState


def _route_from_router(state: AgentState) -> str:
    if state["query_type"] == "escalate":
        return END
    return "retriever"


def _escalate_node(state: AgentState) -> dict:
    return {"final_response": ESCALATION_RESPONSE}


def _increment_retry_node(state: AgentState) -> dict:
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "violations": [],
    }


def _route_from_supervisor(state: AgentState) -> str:
    if state.get("violations") and state.get("retry_count", 0) < MAX_RETRIES:
        return "increment_retry"
    return END


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("router", router_node)
    g.add_node("escalate", _escalate_node)
    g.add_node("retriever", retriever_node)
    g.add_node("synthesiser", synthesiser_node)
    g.add_node("citation_validator", citation_validator_node)
    g.add_node("grounding_check", grounding_check_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("increment_retry", _increment_retry_node)

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
    g.add_conditional_edges("supervisor", _route_from_supervisor, {
        "increment_retry": "increment_retry",
        END: END,
    })
    g.add_edge("increment_retry", "synthesiser")

    return g.compile()


# Module-level compiled graph — import this for use in tests if needed
graph = build_graph()
