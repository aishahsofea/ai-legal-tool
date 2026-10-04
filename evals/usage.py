from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from agent.jev_client import usage_observer as jev_usage_observer
from agent.llm_factory import retry_observer

# Nebius dashboard, 2026-09-28. USD per million tokens, (input, output).
# A model missing here prints "price unknown" and marks the total partial; it
# is never priced at 0.
MODEL_PRICES_PER_MILLION_USD: dict[str, tuple[Decimal, Decimal]] = {
    "nvidia/Nemotron-3-Ultra-550b-a55b": (Decimal("1.00"), Decimal("3.00")),
    "nvidia/Nemotron-3_5-Lightning": (Decimal("0.06"), Decimal("0.24")),
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (Decimal("0.06"), Decimal("0.24")),
    # $0.042 per million input tokens, output free (#193).
    "jev-1.13.0": (Decimal("0.042"), Decimal("0")),
}

_MILLION = Decimal(1_000_000)
_UNKNOWN = "unknown"


def price_usd(model: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    prices = MODEL_PRICES_PER_MILLION_USD.get(model)
    if prices is None:
        return None
    in_price, out_price = prices
    return (in_price * input_tokens + out_price * output_tokens) / _MILLION


def _empty() -> dict[str, int]:
    return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}


class UsageHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict = {}
        self._by_model: dict[str, dict[str, int]] = {}
        self._by_node: dict[str, dict[str, int]] = {}
        self._retries = 0

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, invocation_params=None, **kwargs):
        metadata = metadata or {}
        params = invocation_params or {}
        model = (
            metadata.get("ls_model_name")
            or params.get("model")
            or params.get("model_name")
            or _UNKNOWN
        )
        node = metadata.get("langgraph_node") or _UNKNOWN
        with self._lock:
            self._pending[run_id] = (model, node)

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            model, node = self._pending.pop(run_id, (_UNKNOWN, _UNKNOWN))
        input_tokens = output_tokens = reasoning = 0
        for generations in response.generations:
            for gen in generations:
                usage = getattr(getattr(gen, "message", None), "usage_metadata", None) or {}
                input_tokens += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)
                reasoning += (usage.get("output_token_details") or {}).get("reasoning", 0)
        with self._lock:
            for bucket in (
                self._by_model.setdefault(model, _empty()),
                self._by_node.setdefault(node, _empty()),
            ):
                bucket["calls"] += 1
                bucket["input_tokens"] += input_tokens
                bucket["output_tokens"] += output_tokens
                bucket["reasoning_tokens"] += reasoning

    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            self._pending.pop(run_id, None)

    def record_external(self, model: str, node: str, input_tokens: int, output_tokens: int) -> None:
        """A call that bypasses LangChain (Jev), so on_llm_end never sees it."""
        with self._lock:
            for bucket in (
                self._by_model.setdefault(model, _empty()),
                self._by_node.setdefault(node, _empty()),
            ):
                bucket["calls"] += 1
                bucket["input_tokens"] += input_tokens
                bucket["output_tokens"] += output_tokens

    def record_retry(self) -> None:
        with self._lock:
            self._retries += 1

    def summarize(self) -> dict:
        with self._lock:
            by_model = {m: dict(v) for m, v in self._by_model.items()}
            by_node = {n: dict(v) for n, v in self._by_node.items()}
            retries = self._retries

        total = _empty()
        total_usd = Decimal(0)
        partial = False
        for model, row in by_model.items():
            row["usd"] = price_usd(model, row["input_tokens"], row["output_tokens"])
            if row["usd"] is None:
                partial = True
            else:
                total_usd += row["usd"]
            for key in total:
                total[key] += row[key]
        total["usd"] = total_usd
        return {
            "by_model": by_model,
            "by_node": by_node,
            "total": total,
            "partial": partial,
            "retries": retries,
        }


# Only set inside eval_usage(), so production /query never carries the handler.
_active: ContextVar[UsageHandler | None] = ContextVar("eval_usage_handler", default=None)
register_configure_hook(_active, inheritable=True)


@contextmanager
def eval_usage():
    handler = UsageHandler()
    token = _active.set(handler)
    observer_token = retry_observer.set(handler.record_retry)
    jev_token = jev_usage_observer.set(
        lambda model, i, o: handler.record_external(model, "jev_first_pass", i, o)
    )
    try:
        yield handler
    finally:
        jev_usage_observer.reset(jev_token)
        retry_observer.reset(observer_token)
        _active.reset(token)


def record_retry() -> None:
    handler = _active.get()
    if handler is not None:
        handler.record_retry()


def _usd_json(value: Decimal | None) -> float | None:
    return None if value is None else float(round(value, 6))


def usage_to_json(summary: dict) -> dict:
    """`summarize()` output with Decimal USD turned into floats for results.json."""

    def rows(table: dict[str, dict]) -> dict[str, dict]:
        return {k: {**v, **({"usd": _usd_json(v["usd"])} if "usd" in v else {})} for k, v in table.items()}

    return {
        **summary,
        "by_model": rows(summary["by_model"]),
        "by_node": rows(summary["by_node"]),
        "total": {**summary["total"], "usd": _usd_json(summary["total"]["usd"])},
    }


def _row(label: str, row: dict, usd: str = "") -> str:
    return (
        f"  {label}: {row['calls']} calls, {row['input_tokens']:,} in, "
        f"{row['output_tokens']:,} out ({row['reasoning_tokens']:,} reasoning){usd}"
    )


def format_usage(summary: dict) -> list[str]:
    lines = ["Usage (estimated):"]
    for model, row in summary["by_model"].items():
        usd = f", ${row['usd']:.4f}" if row["usd"] is not None else ", price unknown"
        lines.append(_row(model, row, usd))
    total = summary["total"]
    note = " (partial: models with unknown price are not counted)" if summary["partial"] else ""
    lines.append(_row("total", total, f", ${total['usd']:.4f}{note}"))
    lines.append("By node:")
    for node, row in summary["by_node"].items():
        lines.append(_row(node, row))
    lines.append(
        f"json_mode retries: {summary['retries']}. Token totals are a floor: a call cut off at the "
        "provider reports no usage, so each retry can hide up to ~8,192 output tokens."
    )
    return lines
