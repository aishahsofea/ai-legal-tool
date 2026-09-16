"""Canonical citation identifiers used at every comparison boundary.

Retrieved metadata stores bare identifiers such as ``559`` and ``90A``. LLMs
may return the same identifiers in display form, such as ``Act 559`` or
``Section 90A(1)``. Comparing those raw strings caused valid citations to be
silently discarded, so comparisons must use the canonical key from this module.

The original retrieved values remain authoritative for citation output. These
helpers normalize comparison keys only; they do not rewrite displayed metadata.
"""
from __future__ import annotations

import re
from typing import Any


_ACT_PREFIX_RE = re.compile(
    r"^(?:ACT|AKTA)(?:\s+NO\.?)?\s+",
    re.IGNORECASE,
)
_SECTION_NUMBER_RE = re.compile(
    r"^\s*(?:(?:SECTION|SEKSYEN|ARTICLE|PERKARA|SEC|S)\.?\s*)?"
    r"(\d+[A-Z]{0,2})\b",
    re.IGNORECASE,
)
# ADR 0018's path grammar: `s.<token>` (body) or `sched.<k>` / `sched.<k>/para.<token>`
# / `sched.<k>/art.<token>` (a schedule's own content, or one of its items).
_BODY_PATH_RE = re.compile(r"^s\.\s*(\d{1,3}[A-Za-z]{0,2})$", re.IGNORECASE)
_SCHEDULE_PATH_RE = re.compile(
    r"^sched\.\s*(\d+)(?:\s*/\s*(para|art)\.\s*(\d{1,3}[A-Za-z]{0,2}))?$",
    re.IGNORECASE,
)


def canonicalize_act_number(act_number: Any) -> str:
    """Return a bare, uppercase Act identifier suitable for comparison."""
    value = str(act_number or "").strip()
    return _ACT_PREFIX_RE.sub("", value, count=1).strip().upper()


def canonicalize_section_number(section_number: Any) -> str:
    """Return a bare section identifier, dropping labels and subsections."""
    match = _SECTION_NUMBER_RE.match(str(section_number or ""))
    return match.group(1).upper() if match else ""


def canonicalize_path(value: Any) -> str:
    """Return a canonical path-qualified identifier (ADR 0018), or "" if `value`
    doesn't parse as one."""
    text = str(value or "").strip()
    body_match = _BODY_PATH_RE.match(text)
    if body_match:
        return f"s.{body_match.group(1).upper()}"
    schedule_match = _SCHEDULE_PATH_RE.match(text)
    if not schedule_match:
        return ""
    ordinal, item_kind, token = schedule_match.groups()
    base = f"sched.{ordinal}"
    return f"{base}/{item_kind.lower()}.{token.upper()}" if item_kind else base


def canonicalize_citation_key(
    act_number: Any,
    section_number: Any = "",
    path: Any = None,
) -> tuple[str, str]:
    """Return the single Act/identifier representation used for comparisons.

    Tries `section_number` first, falling back to `path` only when it's empty -
    never the other way round. A body chunk's `section_number` is what an LLM
    was shown and echoes back (`agent/nodes/synthesiser.py`'s `format_chunk`),
    so it must win whenever it's real or the two sides of a comparison stop
    matching. Only a schedule chunk's genuinely empty `section_number` (ADR
    0018) falls through - to the caller's `path` argument if one was given, or
    to `section_number` itself, since an LLM/judge echo has no separate path
    field and a schedule path it echoes back arrives in that same string.
    """
    section = canonicalize_section_number(section_number)
    if not section:
        section = canonicalize_path(path) if path else canonicalize_path(section_number)
    return (canonicalize_act_number(act_number), section)


def normalized_citation_pair(
    act_number: Any, section_number: Any, path: Any = None,
) -> tuple[str, str] | None:
    """Canonical (act, section) pair, or None if either half fails to canonicalize."""
    act, section = canonicalize_citation_key(act_number, section_number, path)
    return (act, section) if act and section else None
