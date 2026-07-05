"""Deterministic citation validation for generated legal answers.

The validator checks citation integrity before the policy supervisor runs. It does
not judge whether the cited text supports a claim; that belongs to the later
span-level grounding check. This node only verifies that cited Act/section pairs
are real within the retrieved context and that at least one structured citation
is present.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.state import AgentState

METADATA_DIR = Path("data/acts_metadata")


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


def citation_validator_node(state: AgentState) -> dict:
    retrieved_chunks = state.get("retrieved_chunks", [])
    citations = state.get("citations", [])

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

    if not structured_keys:
        violations.append("No citation found. A legal answer must cite at least one retrieved section.")

    for act_number, section_number in sorted(structured_keys):
        if not _metadata_exists(act_number):
            violations.append(f"Citation references unknown Act {act_number}.")
        if (act_number, section_number) not in retrieved_keys:
            violations.append(
                f"Citation Section {section_number} of Act {act_number} was not in retrieved sources."
            )

    return {"violations": violations}
