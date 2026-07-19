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


def canonicalize_act_number(act_number: Any) -> str:
    """Return a bare, uppercase Act identifier suitable for comparison."""
    value = str(act_number or "").strip()
    return _ACT_PREFIX_RE.sub("", value, count=1).strip().upper()


def canonicalize_section_number(section_number: Any) -> str:
    """Return a bare section identifier, dropping labels and subsections."""
    match = _SECTION_NUMBER_RE.match(str(section_number or ""))
    return match.group(1).upper() if match else ""


def canonicalize_citation_key(
    act_number: Any,
    section_number: Any,
) -> tuple[str, str]:
    """Return the single Act/section representation used for comparisons."""
    return (
        canonicalize_act_number(act_number),
        canonicalize_section_number(section_number),
    )
