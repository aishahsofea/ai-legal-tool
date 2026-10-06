import json
import os
from collections.abc import Callable
from contextvars import ContextVar

import requests
from langsmith import traceable

_JEV_URL = "https://api.typesafe.ai/v1/systemone"

# `jev-latest` can change under us, so the model is pinned in config.
_FLOATING_MODEL = "jev-latest"

_INSTRUCTIONS = (
    "You verify Malaysian statute research answers. Use only the cited source text in the state; "
    "no outside legal knowledge. Label the whole ANSWER: check every legal claim against the cited "
    "section it relies on. Ignore disclaimers, transitions and background with no Act/section attribution."
)
_CRITERIA = {
    "supported": "every legal claim in the answer is directly supported by the cited section text it relies on.",
    "partial": "at least one claim is only partly supported, or overstates the cited section text.",
    "unsupported": "at least one claim is not supported by any cited section text.",
}


# Set only by evals/usage.py: LangChain callbacks never see Jev calls.
usage_observer: ContextVar[Callable[[str, int, int], None] | None] = ContextVar(
    "jev_usage_observer", default=None
)


class JevError(RuntimeError):
    pass


def _model() -> str:
    model = (os.getenv("JEV_MODEL") or "").strip()
    if not model:
        raise JevError("JEV_MODEL is not set")
    if model == _FLOATING_MODEL:
        raise JevError("JEV_MODEL must be a pinned version, not jev-latest")
    return model


def _trace_inputs(inputs: dict) -> dict:
    # Allowlist, not a denylist: the API key must never reach a run.
    return {"state": inputs["state"], "questions": inputs["questions"]}


@traceable(run_type="llm", name="jev", process_inputs=_trace_inputs)
def _call(state: str, questions: dict, *, key: str, model: str, timeout: float) -> dict:
    """The HTTP call, as its own run so a Jev error shows as a failed `llm` run."""
    body = {"state": state, "model": model, "questions": questions}
    try:
        response = requests.post(
            _JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout
        )
        response.raise_for_status()
        payload = response.json()
        answers = payload["answers"]
        usage = payload.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        observer = usage_observer.get()
        if observer is not None:
            observer(model, input_tokens, output_tokens)
    except requests.exceptions.RequestException as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise JevError(f"Jev response was malformed: {exc!r}") from exc
    if not isinstance(answers, dict):
        raise JevError("Jev response `answers` is not an object")
    return {
        "answers": answers,
        # langsmith lifts this key into the run's token counts.
        "usage_metadata": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _post(questions: dict, state: str, timeout: float) -> dict:
    """Raises JevError on any failure; returns the response's `answers` dict."""
    # Config errors raise here, before any run exists.
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set")
    model = _model()
    result = _call(
        state,
        questions,
        key=key,
        model=model,
        timeout=timeout,
        # The model comes from env, so it can't be a decorator argument.
        langsmith_extra={"metadata": {"ls_provider": "typesafe", "ls_model_name": model}},
    )
    return result["answers"]


def classify(state: str, questions: dict, *, timeout: float = 5.0) -> dict:
    """Ask `questions` of `state`; returns the `answers` dict. Raises JevError on any failure."""
    return _post(questions, state, timeout)


def supported_probability(answer: str, sources: list[dict], *, timeout: float = 5.0) -> float:
    """P(every claim in `answer` is `supported`) against the cited `sources`; raises JevError on any failure."""
    answers = _post(
        {"verdict": {"type": "choice", "instructions": _INSTRUCTIONS, "criteria": _CRITERIA}},
        # Same payload as the Ultra judge's `_messages`, so both judges see the same answer.
        json.dumps({"cited_sources": sources, "answer": answer}, ensure_ascii=False, indent=2),
        timeout,
    )
    try:
        probability = float(answers["verdict"]["probabilities"]["supported"])
    except (ValueError, KeyError, TypeError) as exc:
        raise JevError(f"Jev response had no usable `supported` probability: {exc!r}") from exc
    if not 0.0 <= probability <= 1.0:
        raise JevError(f"Jev returned an out-of-range probability: {probability}")
    return probability
