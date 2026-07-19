"""Deterministic citation validation for generated legal answers.

The validator checks citation integrity before the policy supervisor runs. It does
not judge whether the cited text supports a claim; that belongs to the later
span-level grounding check. This node only verifies that cited Act/section pairs
are real within the retrieved context and that at least one structured citation
is present.
"""
from __future__ import annotations

from pathlib import Path

from agent.citation_keys import canonicalize_citation_key
from agent.state import AgentState

METADATA_DIR = Path("data/acts_metadata")

def _metadata_exists(act_number: str) -> bool:
    if not act_number or act_number == "FC":
        return True
    return (METADATA_DIR / f"{act_number}.json").exists()


def citation_validator_node(state: AgentState) -> dict:
    retrieved_chunks = state.get("retrieved_chunks", [])
    citations = state.get("citations", [])

    retrieved_keys = {
        canonicalize_citation_key(chunk.get("act_number"), chunk.get("section_number"))
        for chunk in retrieved_chunks
    }
    structured_keys = {
        canonicalize_citation_key(citation.get("act_number"), citation.get("section_number"))
        for citation in citations
    }
    structured_keys.discard(("", ""))

    violations = list(state.get("violations", []))
    # Evidence-shaped violations are tracked separately so the retry can route to
    # re-retrieval (fetch better sources) rather than a blind re-draft (Phase 4).
    evidence_violations = list(state.get("evidence_violations", []))

    def _flag(msg: str) -> None:
        violations.append(msg)
        evidence_violations.append(msg)

    if not structured_keys:
        _flag("No citation found. A legal answer must cite at least one retrieved section.")

    for act_number, section_number in sorted(structured_keys):
        if not _metadata_exists(act_number):
            _flag(f"Citation references unknown Act {act_number}.")
        if (act_number, section_number) not in retrieved_keys:
            _flag(f"Citation Section {section_number} of Act {act_number} was not in retrieved sources.")

    return {"violations": violations, "evidence_violations": evidence_violations}
