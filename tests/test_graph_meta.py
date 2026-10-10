import pytest

from agent.graph import build_graph
from agent.graph_meta import EDGE_LABELS, NODE_META
from agent.state import AgentState

_ENDPOINTS = {"__start__", "__end__"}


@pytest.fixture(params=["0", "1"], autouse=True)
def agentic_flag(request, monkeypatch):
    monkeypatch.setenv("AGENTIC_RETRIEVAL", request.param)


def _graph():
    return build_graph().get_graph()


def test_node_ids_match_graph():
    real = set(_graph().nodes) - _ENDPOINTS
    assert set(NODE_META) == real


def test_edge_labels_match_conditional_edges():
    conditional = {(e.source, e.target) for e in _graph().edges if e.conditional}
    assert set(EDGE_LABELS) == conditional


def test_reads_and_writes_are_state_fields():
    fields = set(AgentState.__annotations__)
    for node, meta in NODE_META.items():
        unknown = (set(meta.reads) | set(meta.writes)) - fields
        assert not unknown, f"{node}: {unknown}"


def test_positions_are_unique():
    positions = [(m.rank, m.lane) for m in NODE_META.values()]
    assert len(positions) == len(set(positions))
