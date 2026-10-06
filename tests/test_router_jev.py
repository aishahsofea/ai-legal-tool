from unittest.mock import patch

import pytest

from agent.jev_client import JevError
from agent.nodes import router_jev


@pytest.fixture
def jev_on(monkeypatch):
    monkeypatch.delenv("ROUTER_JEV_ENABLED", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("JEV_MODEL", "jev-2026-01")


def _answers(query_type="topical", language="en", probability=0.9):
    return {
        "query_type": {"choice": query_type, "probabilities": {query_type: probability}},
        "response_language": {"choice": language, "probabilities": {language: 0.8}},
    }


def _state(**extra):
    return {"query": "which laws cover data privacy?", "history": [], **extra}


def _route(answers, state=None):
    with patch("agent.jev_client.classify", return_value=answers) as classify:
        return router_jev.jev_route(state or _state()), classify


def test_returns_type_language_and_probability(jev_on):
    out, _ = _route(_answers("statute_lookup", "bm", 0.77))
    assert out == {"query_type": "statute_lookup", "response_language": "bm", "query_type_probability": 0.77}


def test_sends_history_and_query_with_short_timeout(jev_on):
    history = [{"role": "user", "content": "PDPA"}, {"role": "assistant", "content": "ok"}]
    _, classify = _route(_answers(), _state(query="section 5?", history=history))
    state_text = classify.call_args.args[0]
    assert "user: PDPA" in state_text and "Current query:\nsection 5?" in state_text
    assert classify.call_args.args[1] is router_jev.QUESTIONS
    assert classify.call_args.kwargs["timeout"] == 2.0


@pytest.mark.parametrize("missing", ["TYPESAFE_API_KEY", "JEV_MODEL"])
def test_disabled_without_jev_config(jev_on, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with patch("agent.jev_client.classify") as classify:
        assert router_jev.jev_route(_state()) is None
    classify.assert_not_called()


def test_on_by_default_when_jev_configured(jev_on):
    assert router_jev.enabled()
    out, classify = _route(_answers())
    assert out is not None
    classify.assert_called_once()


@pytest.mark.parametrize("value", ["", "on", "1", "true"])
def test_flag_other_values_leave_it_on(jev_on, monkeypatch, value):
    monkeypatch.setenv("ROUTER_JEV_ENABLED", value)
    assert router_jev.enabled()


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false", "no"])
def test_flag_off_values_disable(jev_on, monkeypatch, value):
    monkeypatch.setenv("ROUTER_JEV_ENABLED", value)
    with patch("agent.jev_client.classify") as classify:
        assert router_jev.jev_route(_state()) is None
    classify.assert_not_called()


def test_client_error_propagates(jev_on):
    with patch("agent.jev_client.classify", side_effect=JevError("boom")):
        with pytest.raises(JevError):
            router_jev.jev_route(_state())


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"query_type": {"choice": "topical", "probabilities": {"topical": 0.9}}},
        _answers("escalate"),
        _answers(language="fr"),
        {"query_type": {"choice": "topical"}, "response_language": {"choice": "en"}},
        _answers(probability=1.5),
        _answers(probability="high"),
        {"query_type": None, "response_language": None},
    ],
)
def test_bad_shape_raises(jev_on, answers):
    with pytest.raises(JevError):
        _route(answers)


# --- clarify question writer (Phase 5) ---

import asyncio

from agent.nodes import router


def _writer_state():
    return {"query": "what does section 5 say?", "history": []}


def test_clarify_question_written():
    with patch.object(router, "_clarify_llm") as llm:
        llm.invoke.return_value = router._ClarifyOutput(clarifying_question="  Which Act's section 5?  ")
        assert router.write_clarifying_question(_writer_state()) == "Which Act's section 5?"
    system = llm.invoke.call_args.args[0][0]["content"]
    assert "clarifying_question" in system


def test_clarify_question_empty_stays_empty():
    with patch.object(router, "_clarify_llm") as llm:
        llm.invoke.return_value = router._ClarifyOutput(clarifying_question="")
        assert router.write_clarifying_question(_writer_state()) == ""


def test_clarify_llm_raises_returns_empty():
    with patch.object(router, "_clarify_llm") as llm:
        llm.invoke.side_effect = RuntimeError("down")
        assert router.write_clarifying_question(_writer_state()) == ""


def test_async_clarify_written_and_raises():
    async def ok(*_a, **_k):
        return router._ClarifyOutput(clarifying_question="Which Act?")

    async def boom(*_a, **_k):
        raise RuntimeError("down")

    with patch.object(router, "_clarify_llm") as llm:
        llm.ainvoke = ok
        assert asyncio.run(router.awrite_clarifying_question(_writer_state())) == "Which Act?"
        llm.ainvoke = boom
        assert asyncio.run(router.awrite_clarifying_question(_writer_state())) == ""


# --- wiring with fail-open (Phase 6) ---

import logging
from contextlib import ExitStack

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.graph import build_graph
from agent.nodes.router import _RouterOutput
from tests.test_clarify_interrupt import AMBIGUOUS, ANSWER, _patch_sync_happy_path


def _llm_out(query_type="topical", language="en"):
    return _RouterOutput(reasoning="r", query_type=query_type, response_language=language)


def _jev_out(query_type="topical", language="bm", probability=0.9):
    return {"query_type": query_type, "response_language": language, "query_type_probability": probability}


def _run(node, state):
    paths: list[str] = []
    token = router_jev.route_path_observer.set(paths.append)
    try:
        out = asyncio.run(node(state)) if asyncio.iscoroutinefunction(node) else node(state)
    finally:
        router_jev.route_path_observer.reset(token)
    return out, paths


@pytest.fixture(params=["sync", "async"])
def node(request):
    return router.router_node if request.param == "sync" else router.arouter_node


@pytest.fixture
def llm():
    async def ainvoke(*_a, **_k):
        return llm.result

    with patch.object(router, "_structured_llm") as mock:
        mock.invoke.side_effect = lambda *_a, **_k: llm.result
        mock.ainvoke = ainvoke
        llm = mock
        llm.result = _llm_out("statute_lookup", "en")
        yield mock


def test_jev_result_skips_llm_and_drops_probability(jev_on, llm, node):
    with patch("agent.jev_client.classify", return_value=_answers("topical", "bm", 0.9)):
        out, paths = _run(node, _state())
    assert out == {"query_type": "topical", "response_language": "bm"}
    assert paths == ["jev"]
    llm.invoke.assert_not_called()


def test_jev_probability_logged(jev_on, llm, node, caplog):
    with caplog.at_level(logging.INFO, logger="agent.nodes.router"):
        with patch("agent.jev_client.classify", return_value=_answers("topical", "en", 0.912)):
            _run(node, _state())
    assert "topical p=0.912" in caplog.text


def test_jev_error_falls_back_to_llm(jev_on, llm, node, caplog):
    with patch("agent.jev_client.classify", side_effect=JevError("down")):
        out, paths = _run(node, _state())
    assert out == {"query_type": "statute_lookup", "response_language": "en"}
    assert paths == ["fallback"]
    assert "falling back" in caplog.text


@pytest.mark.parametrize("missing", ["TYPESAFE_API_KEY", "JEV_MODEL"])
def test_missing_config_uses_llm_without_calling_jev(jev_on, llm, node, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with patch("agent.jev_client.classify") as classify:
        out, paths = _run(node, _state())
    assert out["query_type"] == "statute_lookup"
    assert paths == ["llm"]
    classify.assert_not_called()


def test_flag_off_uses_llm_without_calling_jev(jev_on, llm, node, monkeypatch):
    monkeypatch.setenv("ROUTER_JEV_ENABLED", "off")
    with patch("agent.jev_client.classify") as classify:
        out, paths = _run(node, _state())
    assert out["query_type"] == "statute_lookup"
    assert paths == ["llm"]
    classify.assert_not_called()


def test_jev_floating_model_falls_back(jev_on, llm, node, monkeypatch):
    monkeypatch.setenv("JEV_MODEL", "jev-latest")
    out, paths = _run(node, _state())
    assert out["query_type"] == "statute_lookup"
    assert paths == ["fallback"]


def test_escalation_fires_before_jev(jev_on, llm, node):
    with patch("agent.jev_client.classify") as classify:
        out, paths = _run(node, _state(query="am i liable for this?"))
    assert out["query_type"] == "escalate"
    classify.assert_not_called()
    llm.invoke.assert_not_called()
    assert paths == []


def test_jev_clarify_gets_question_from_writer(jev_on, llm, node):
    with patch("agent.jev_client.classify", return_value=_answers("clarify", "en")), patch.object(
        router, "_clarify_llm"
    ) as writer:
        writer.invoke.side_effect = lambda *_a, **_k: router._ClarifyOutput(clarifying_question="Which Act?")

        async def ainvoke(*_a, **_k):
            return router._ClarifyOutput(clarifying_question="Which Act?")

        writer.ainvoke = ainvoke
        out, _ = _run(node, _state())
    assert out == {"query_type": "clarify", "response_language": "en", "clarifying_question": "Which Act?"}


def test_jev_clarify_writer_failure_gives_empty_question(jev_on, llm, node):
    with patch("agent.jev_client.classify", return_value=_answers("clarify", "en")), patch.object(
        router, "_clarify_llm"
    ) as writer:
        writer.invoke.side_effect = RuntimeError("down")
        writer.ainvoke.side_effect = RuntimeError("down")
        out, paths = _run(node, _state())
    assert out["query_type"] == "clarify" and out["clarifying_question"] == ""
    assert paths == ["jev"]


def test_graph_falls_through_on_empty_clarify_question(jev_on):
    seen: dict = {}
    with ExitStack() as stack:
        _patch_sync_happy_path(stack, router.router_node, seen)
        stack.enter_context(patch("agent.jev_client.classify", return_value=_answers("clarify", "en")))
        writer = stack.enter_context(patch.object(router, "_clarify_llm"))
        writer.invoke.return_value = router._ClarifyOutput(clarifying_question="")
        app = build_graph(MemorySaver())
        out = app.invoke({"query": AMBIGUOUS}, {"configurable": {"thread_id": "jev-empty", "user_id": None}})
    assert "__interrupt__" not in out
    assert seen["retriever_query"] == AMBIGUOUS


def test_graph_clarifies_once_with_jev_router(jev_on):
    seen: dict = {}
    config = {"configurable": {"thread_id": "jev-once", "user_id": None}}
    with ExitStack() as stack:
        _patch_sync_happy_path(stack, router.router_node, seen)
        stack.enter_context(patch("agent.jev_client.classify", return_value=_answers("clarify", "en")))
        writer = stack.enter_context(patch.object(router, "_clarify_llm"))
        writer.invoke.return_value = router._ClarifyOutput(clarifying_question="Which Act?")
        app = build_graph(MemorySaver())
        paused = app.invoke({"query": AMBIGUOUS}, config)
        assert "__interrupt__" in paused
        resumed = app.invoke(Command(resume=ANSWER), config)
    assert "__interrupt__" not in resumed
    assert "retriever_query" in seen
