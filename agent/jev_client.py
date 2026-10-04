"""Jev (TypeSafe AI) client for the grounding first pass (#201).

Raises on every failure: the caller owns the fail-open decision.
"""
import os
from collections.abc import Callable
from contextvars import ContextVar

import requests

_JEV_URL = "https://api.typesafe.ai/v1/systemone"

# `jev-latest` can change under us, so the model is pinned in config (#190).
_FLOATING_MODEL = "jev-latest"

_INSTRUCTIONS = (
    "You verify Malaysian statute research claims. Use only the cited source text in the state; "
    "no outside legal knowledge. Label the CLAIM against the cited section text."
)
_CRITERIA = {
    "supported": "the cited section text directly supports the claim.",
    "partial": "the cited section text supports only part of the claim or the claim overstates the text.",
    "unsupported": "the cited section text does not support the claim.",
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


def supported_probability(claim: str, source: str, *, timeout: float = 5.0) -> float:
    """P(`supported`) of `claim` against its cited `source` text. Raises JevError on any failure."""
    key = os.getenv("TYPESAFE_API_KEY")
    if not key:
        raise JevError("TYPESAFE_API_KEY is not set")
    model = _model()

    body = {
        "state": f"CITED SOURCE:\n{source}\n\nCLAIM:\n{claim}",
        "model": model,
        "questions": {
            "verdict": {"type": "choice", "instructions": _INSTRUCTIONS, "criteria": _CRITERIA}
        },
    }
    try:
        response = requests.post(
            _JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout
        )
        response.raise_for_status()
        payload = response.json()
        probabilities = payload["answers"]["verdict"]["probabilities"]
        probability = float(probabilities["supported"])
        usage = payload.get("usage") or {}
    except requests.exceptions.RequestException as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise JevError(f"Jev response had no usable `supported` probability: {exc!r}") from exc
    if not 0.0 <= probability <= 1.0:
        raise JevError(f"Jev returned an out-of-range probability: {probability}")
    observer = usage_observer.get()
    if observer is not None:
        observer(model, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
    return probability
