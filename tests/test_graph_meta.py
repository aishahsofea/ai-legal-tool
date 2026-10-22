import ast
import inspect
import sys
import textwrap

import pytest

from agent.graph import build_graph
from agent.graph_meta import EDGE_LABELS, NODE_META
from agent.nodes import retriever as retriever_module
from agent.state import AgentState

_ENDPOINTS = {"__start__", "__end__"}


def _dict_keys(node: ast.Dict) -> set[str]:
    # None keys are **spread entries: dynamic keys are out of reach for a static check.
    return {
        k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _local_keys(tree: ast.AST, name: str) -> set[str]:
    keys: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for target in n.targets:
                if isinstance(target, ast.Name) and target.id == name and isinstance(n.value, ast.Dict):
                    keys |= _dict_keys(n.value)
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == name
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    keys.add(target.slice.value)
    return keys


def _returned_keys(fn, seen: set | None = None) -> set[str]:
    seen = set() if seen is None else seen
    if fn in seen:
        return set()
    seen.add(fn)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError):
        return set()
    module = sys.modules[fn.__module__]
    keys: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Return) or n.value is None:
            continue
        value = n.value
        if isinstance(value, ast.Dict):
            keys |= _dict_keys(value)
        elif isinstance(value, ast.Name):
            keys |= _local_keys(tree, value.id)
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            target = getattr(module, value.func.id, None)
            if inspect.isfunction(target) and target.__module__ == module.__name__:
                keys |= _returned_keys(target, seen)
    return keys


def _node_functions(node: str):
    bound = build_graph().nodes[node].bound
    fns = [f for f in (getattr(bound, "func", None), getattr(bound, "afunc", None)) if f]
    if node == "retriever":
        fns += [retriever_module.retriever_node, retriever_module.agentic_retriever_node]
    return fns


def _collected(node: str) -> set[str]:
    keys: set[str] = set()
    for fn in _node_functions(node):
        keys |= _returned_keys(fn)
    return keys


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


@pytest.mark.parametrize("node", sorted(NODE_META))
def test_returned_keys_are_declared_writes(node):
    extra = _collected(node) - set(NODE_META[node].writes)
    assert not extra, f"{node} returns undeclared keys: {extra}"


@pytest.mark.parametrize("node", sorted(NODE_META))
def test_collector_finds_writes(node):
    assert _collected(node)
