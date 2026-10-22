import re
from dataclasses import replace

import pytest

from agent.graph_meta import EDGE_LABELS, NODE_META
from agent.state import AgentState
from scripts.render_graph_map import CONTRIBUTING, _field_table, current_block, render


@pytest.fixture(params=["0", "1"], autouse=True)
def agentic_flag(request, monkeypatch):
    monkeypatch.setenv("AGENTIC_RETRIEVAL", request.param)


def _mermaid() -> str:
    return re.search(r"```mermaid\n(.*?)```", render(), re.S).group(1)


def test_node_declarations():
    declared = re.findall(r"^\s+(\w+)(?:\[|\(\[)", _mermaid(), re.M)
    assert set(NODE_META) <= set(declared)
    assert {"graph_start", "graph_end"} <= set(declared)
    graph_nodes = [n for n in declared if n not in {"legend_llm", "legend_deterministic", "legend_control"}]
    assert len(graph_nodes) == len(NODE_META) + 2


def test_edge_count():
    edges = re.findall(r"^\s+\w+ (?:-->|-\. .* \.->) \w+$", _mermaid(), re.M)
    assert len(edges) == 23


def test_conditional_edges_are_dashed_and_labelled():
    mermaid = _mermaid()
    for label in EDGE_LABELS.values():
        assert f'-. "{label}" .->' in mermaid


def test_styles_and_legend():
    mermaid = _mermaid()
    for kind in ("llm", "deterministic", "control"):
        assert f"classDef {kind} " in mermaid
    assert "subgraph legend" in mermaid


def test_field_table_has_one_row_per_state_field():
    section = render().split("| Field | Written by |")[1]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert [r.split("`")[1] for r in rows] == list(AgentState.__annotations__)


def test_router_row_lists_complexity():
    row = next(l for l in render().splitlines() if l.startswith("| `complexity` |"))
    assert "`router`" in row


def test_unwritten_field_is_input(monkeypatch):
    clarify = NODE_META["clarify"]
    writes = tuple(w for w in clarify.writes if w != "query")
    monkeypatch.setitem(NODE_META, "clarify", replace(clarify, writes=writes))
    row = next(l for l in _field_table().splitlines() if l.startswith("| `query` |"))
    assert "(input)" in row


def test_contributing_graph_map_is_current():
    assert current_block(CONTRIBUTING.read_text()) == render(), (
        "Graph map is stale: run python -m scripts.render_graph_map"
    )
