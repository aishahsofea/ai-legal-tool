"""One spelling rule for every boolean env flag.

Four parsers had drifted apart: `AGENTIC_RETRIEVAL` rejected `on`, the Semantic
Memory flags accepted nothing but `on`, and two of them never stripped
whitespace. An operator copying the spelling from a neighbouring flag in
CONTRIBUTING.md got a silent no-op. Worse, agent/query_lifecycle.py already
used the permissive set to stamp flag state onto LangSmith traces, so
`AGENTIC_RETRIEVAL=on` recorded a run as agentic that had in fact taken the
deterministic path.
"""
import os

_TRUE_VALUES = {"1", "true", "yes", "on"}


def parse_feature_flag(value: str | None) -> bool:
    """Unknown and unset values stay off — a flag nobody set must never read as on."""
    return str(value or "").strip().casefold() in _TRUE_VALUES


def flag_enabled(name: str) -> bool:
    return parse_feature_flag(os.getenv(name))
