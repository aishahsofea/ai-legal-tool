"""Deterministic citation validation for generated legal answers.

The validator checks citation integrity before the policy supervisor runs. It does
not judge whether the cited text supports a claim; that belongs to the later
span-level grounding check. This node only verifies that cited Act/section pairs
are real within the retrieved context and that prose citations are mirrored by
structured citations.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.state import AgentState

METADATA_DIR = Path("data/acts_metadata")

_PROSE_CITATION_RE = re.compile(
    r"\bsection\s+(\d+[A-Z]{0,2})(?:\([^)]*\))*\s+of\s+(?:the\s+)?([^.;\n]{2,90})",
    re.IGNORECASE,
)
_ACT_NUMBER_RE = re.compile(r"\bact\s+(\d+[A-Z]?)\b", re.IGNORECASE)
_STOP_WORDS = {
    "the",
    "act",
    "akta",
    "of",
    "and",
    "section",
    "subsection",
    "code",
    "1950",
    "1955",
    "2010",
    "2012",
    "2016",
}
_ACT_ALIASES: dict[str, str] = {
    "pdpa": "709",
    "personal data protection act": "709",
    "evidence act": "56",
    "penal code": "574",
    "criminal procedure code": "593",
    "cpc": "593",
    "employment act": "265",
    "companies act": "777",
    "federal constitution": "FC",
}


def _normalise_section(section: Any) -> str:
    """Return canonical section key, dropping subsection suffixes."""
    match = re.match(r"\s*(\d+[A-Z]{0,2})", str(section or ""), re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _key(act_number: Any, section_number: Any) -> tuple[str, str]:
    return (str(act_number or "").upper(), _normalise_section(section_number))


def _metadata_exists(act_number: str) -> bool:
    if not act_number or act_number == "FC":
        return True
    return (METADATA_DIR / f"{act_number}.json").exists()


def _meaningful_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if word not in _STOP_WORDS and len(word) > 1}


def _resolve_prose_act(phrase: str, retrieved_chunks: list[dict]) -> str | None:
    phrase_lower = phrase.lower()

    for alias, act_number in _ACT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", phrase_lower):
            return act_number

    phrase_words = _meaningful_words(phrase)
    if not phrase_words:
        return None

    for chunk in retrieved_chunks:
        title_words = _meaningful_words(str(chunk.get("act_title", "")))
        if phrase_words and phrase_words.issubset(title_words):
            return str(chunk.get("act_number", "")).upper()

    number_match = _ACT_NUMBER_RE.search(phrase)
    if number_match:
        return number_match.group(1).upper()

    return None


def _extract_prose_citation_keys(answer: str, retrieved_chunks: list[dict]) -> set[tuple[str, str]]:
    keys = set()
    for match in _PROSE_CITATION_RE.finditer(answer):
        section = _normalise_section(match.group(1))
        act_number = _resolve_prose_act(match.group(2), retrieved_chunks)
        if act_number and section:
            keys.add((act_number, section))
    return keys


def citation_validator_node(state: AgentState) -> dict:
    retrieved_chunks = state.get("retrieved_chunks", [])
    citations = state.get("citations", [])
    answer = state.get("draft_response", "")

    retrieved_keys = {
        _key(chunk.get("act_number"), chunk.get("section_number"))
        for chunk in retrieved_chunks
    }
    structured_keys = {
        _key(citation.get("act_number"), citation.get("section_number"))
        for citation in citations
    }
    structured_keys.discard(("", ""))

    violations = list(state.get("violations", []))

    for act_number, section_number in sorted(structured_keys):
        if not _metadata_exists(act_number):
            violations.append(f"Citation references unknown Act {act_number}.")
        if (act_number, section_number) not in retrieved_keys:
            violations.append(
                f"Citation Section {section_number} of Act {act_number} was not in retrieved sources."
            )

    prose_keys = _extract_prose_citation_keys(answer, retrieved_chunks)
    for act_number, section_number in sorted(prose_keys):
        if (act_number, section_number) not in retrieved_keys:
            violations.append(
                f"Prose citation Section {section_number} of Act {act_number} was not in retrieved sources."
            )
        if (act_number, section_number) not in structured_keys:
            violations.append(
                f"Prose citation Section {section_number} of Act {act_number} is missing from structured citations."
            )

    return {"violations": violations}
