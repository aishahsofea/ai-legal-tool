import asyncio
from decimal import Decimal
from uuid import uuid4

from langchain_core.callbacks import CallbackManager
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from pydantic import BaseModel

from agent.llm_factory import structured_llm

from evals.usage import (
    MODEL_PRICES_PER_MILLION_USD,
    UsageHandler,
    eval_usage,
    format_usage,
    price_usd,
    record_retry,
    usage_to_json,
)

ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"


def _call(handler, model, node, input_tokens, output_tokens, reasoning=None):
    run_id = uuid4()
    metadata = {"langgraph_node": node} if node else {}
    handler.on_chat_model_start(
        {}, [[]], run_id=run_id, metadata=metadata, invocation_params={"model": model}
    )
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if reasoning is not None:
        usage["output_token_details"] = {"reasoning": reasoning}
    message = AIMessage(content="x", usage_metadata=usage)
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)


def test_tally_sums_by_model_and_node():
    h = UsageHandler()
    _call(h, ULTRA, "synthesiser", 1000, 200, reasoning=150)
    _call(h, ULTRA, "synthesiser", 500, 100, reasoning=40)
    _call(h, LIGHTNING, "router", 300, 20)

    s = h.summarize()

    assert s["by_model"][ULTRA]["calls"] == 2
    assert s["by_model"][ULTRA]["input_tokens"] == 1500
    assert s["by_model"][ULTRA]["output_tokens"] == 300
    assert s["by_model"][ULTRA]["reasoning_tokens"] == 190
    assert s["by_node"]["synthesiser"]["input_tokens"] == 1500
    assert s["by_node"]["router"]["output_tokens"] == 20


def test_missing_reasoning_detail_counts_zero_for_that_call():
    h = UsageHandler()
    _call(h, LIGHTNING, "router", 300, 20)
    assert h.summarize()["by_model"][LIGHTNING]["reasoning_tokens"] == 0


def test_missing_node_metadata_falls_back_to_unknown():
    h = UsageHandler()
    _call(h, ULTRA, None, 10, 5)
    assert "unknown" in h.summarize()["by_node"]


def test_price_lookup_known_and_unknown():
    assert ULTRA in MODEL_PRICES_PER_MILLION_USD
    # 1M in + 1M out at $1.00 / $3.00
    assert price_usd(ULTRA, 1_000_000, 1_000_000) == Decimal("4.00")
    assert price_usd("claude-judge-not-priced", 10, 10) is None


def test_unknown_price_is_never_zero_and_marks_total_partial():
    h = UsageHandler()
    _call(h, ULTRA, "synthesiser", 1_000_000, 0)
    _call(h, "claude-judge-not-priced", "judge", 100, 100)

    s = h.summarize()

    assert s["by_model"]["claude-judge-not-priced"]["usd"] is None
    assert s["by_model"][ULTRA]["usd"] == Decimal("1.00")
    assert s["total"]["usd"] == Decimal("1.00")
    assert s["partial"] is True


def test_fully_priced_run_is_not_partial():
    h = UsageHandler()
    _call(h, ULTRA, "synthesiser", 10, 10)
    assert h.summarize()["partial"] is False


def test_handler_absent_outside_eval_usage():
    handlers = CallbackManager.configure().handlers
    assert not any(isinstance(x, UsageHandler) for x in handlers)


def test_handler_present_inside_eval_usage_and_removed_after():
    with eval_usage() as h:
        handlers = CallbackManager.configure().handlers
        assert h in handlers
    handlers = CallbackManager.configure().handlers
    assert not any(isinstance(x, UsageHandler) for x in handlers)


def test_record_retry_counts_only_inside_eval_usage():
    record_retry()  # no active handler: must not raise
    with eval_usage() as h:
        record_retry()
        record_retry()
    assert h.summarize()["retries"] == 2


class _SchemaFail(Exception):
    status_code = 422


class _Out(BaseModel):
    answer: str


class _FakeRunnable:
    def __init__(self, fail: bool):
        self._fail = fail

    def invoke(self, *args, **kwargs):
        if self._fail:
            raise _SchemaFail("bad schema")
        return "ok"

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)


class _FakeLLM:
    def with_structured_output(self, schema, method=None):
        return _FakeRunnable(fail=method is None)


def _structured():
    return structured_llm(_FakeLLM(), _Out, node="router", model_name=LIGHTNING)


_MESSAGES = [{"role": "user", "content": "hi"}]


def test_sync_json_mode_retry_is_counted_once():
    with eval_usage() as h:
        assert _structured().invoke(_MESSAGES) == "ok"
    assert h.summarize()["retries"] == 1


def test_async_json_mode_retry_is_counted_once():
    with eval_usage() as h:
        assert asyncio.run(_structured().ainvoke(_MESSAGES)) == "ok"
    assert h.summarize()["retries"] == 1


def test_retry_outside_eval_usage_does_not_raise():
    assert _structured().invoke(_MESSAGES) == "ok"


def _summary_with_unpriced():
    h = UsageHandler()
    _call(h, ULTRA, "synthesiser", 1000, 200, reasoning=150)
    _call(h, "claude-judge-not-priced", "judge", 100, 100)
    record = h.record_retry
    record()
    return h.summarize()


def test_usage_to_json_round_trips_through_json():
    import json

    payload = usage_to_json(_summary_with_unpriced())
    decoded = json.loads(json.dumps(payload))
    assert decoded["by_model"][ULTRA]["usd"] == 0.0016
    assert decoded["by_model"]["claude-judge-not-priced"]["usd"] is None
    assert decoded["partial"] is True
    assert decoded["retries"] == 1


def test_format_usage_flags_unknown_price_partial_total_and_retry_floor():
    text = "\n".join(format_usage(_summary_with_unpriced()))
    assert "price unknown" in text
    assert "partial" in text
    assert "synthesiser" in text
    assert "8,192" in text


def test_build_report_carries_usage_and_defaults_to_empty():
    from evals.run_evals import _build_report

    with_usage = _build_report("full", [], usage=_summary_with_unpriced())
    assert with_usage["summary"]["usage"]["retries"] == 1

    default = _build_report("full", [])
    assert default["summary"]["usage"]["total"]["calls"] == 0
    assert default["summary"]["usage"]["partial"] is False


def test_jev_call_is_priced_and_attributed_through_the_observer(monkeypatch):
    import requests

    from agent import jev_client

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "answers": {"verdict": {"probabilities": {"supported": 0.9}}},
                "usage": {"input_tokens": 1_000_000, "output_tokens": 50},
            }

    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("JEV_MODEL", "jev-1.13.0")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response())

    with eval_usage() as handler:
        jev_client.supported_probability("answer", [])

    summary = handler.summarize()
    assert summary["by_node"]["jev_first_pass"]["calls"] == 1
    assert summary["by_model"]["jev-1.13.0"]["usd"] == Decimal("0.042")
    assert not summary["partial"]
