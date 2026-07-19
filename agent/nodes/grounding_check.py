"""Span-level grounding check for generated legal answers.

This node asks an LLM judge to verify whether legal claims in the draft answer are
supported by the cited retrieved statute sections. It intentionally runs after
citation validation, so it can assume citation references are structurally sane.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from agent.llm_factory import make_llm
from agent.state import AgentState
from citation_receipts.locator import contains_normalized_sequence, normalized_tokens

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = os.getenv("GROUNDING_MODEL", "claude-sonnet-4-6")
_llm = make_llm(_MODEL)


class _GroundingClaim(BaseModel):
    claim: str = Field(description="A sentence or clause from the answer that makes a legal claim.")
    cited_act_number: str = Field(description="Act number used to support the claim.")
    cited_section_number: str = Field(description="Section number used to support the claim.")
    support: Literal["supported", "partial", "unsupported"]
    reason: str
    quote: str = Field(
        default="",
        description="A short contiguous verbatim quote from the cited source supporting this claim.",
    )


class _GroundingOutput(BaseModel):
    claims: list[_GroundingClaim]

    @field_validator("claims", mode="before")
    @classmethod
    def _coerce_claims(cls, value: object) -> object:
        """Tolerate models that return the claims list as a JSON-encoded string."""
        if isinstance(value, str):
            return json.loads(value)
        return value


_grounding_llm = _llm.with_structured_output(_GroundingOutput)

_SYSTEM = """You are a strict grounding verifier for Malaysian statute research answers.

Task:
- Identify every sentence or clause in the answer that makes a legal claim.
- For each legal claim, decide whether the cited statute section text supports it.
- Use only the provided cited source text. Do not use outside legal knowledge.

Labels:
- supported: the cited section text directly supports the claim.
- partial: the cited section text supports only part of the claim or the claim overstates the text.
- unsupported: the cited section text does not support the claim.

For every supported claim, copy one short, contiguous supporting quote from the cited
source into quote. Do not paraphrase, splice passages, or add ellipses. For partial or
unsupported claims, return an empty quote.

Ignore non-legal text such as disclaimers, transitions, headings, and source labels.
Return only the structured result."""


def _normalise_section(section: object) -> str:
    return str(section or "").upper()


def _collect_cited_sources(state: AgentState) -> list[dict]:
    retrieved_lookup = {
        (str(chunk.get("act_number", "")), _normalise_section(chunk.get("section_number"))): chunk
        for chunk in state.get("retrieved_chunks", [])
    }

    sources = []
    seen = set()
    for citation in state.get("citations", []):
        key = (str(citation.get("act_number", "")), _normalise_section(citation.get("section_number")))
        if key in seen:
            continue
        seen.add(key)
        chunk = retrieved_lookup.get(key)
        if not chunk:
            continue
        sources.append({
            "act_number": chunk.get("act_number", ""),
            "act_title": chunk.get("act_title", ""),
            "section_number": chunk.get("section_number", ""),
            "content": chunk.get("content", ""),
        })
    return sources


def _messages(answer: str, sources: list[dict]) -> list[dict]:
    payload = {"answer": answer, "cited_sources": sources}
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _finalise(result: _GroundingOutput, state: AgentState, violations: list[str]) -> dict:
    # An unsupported claim is an evidence gap: the retry should re-retrieve better
    # sources (Phase 4), so these are tracked in evidence_violations too.
    evidence_violations = list(state.get("evidence_violations", []))
    citations = []
    for original in state.get("citations", []):
        citation = dict(original)
        receipt = original.get("receipt")
        if isinstance(receipt, dict):
            # Evidence belongs to this grounding pass only. Copy the nested value so
            # retries cannot mutate or inherit a rejected draft's spans in place.
            citation["receipt"] = {**receipt, "evidence": []}
        citations.append(citation)
    citation_lookup = {
        (str(citation.get("act_number", "")), _normalise_section(citation.get("section_number"))): citation
        for citation in citations
    }
    chunk_lookup = {
        (str(chunk.get("act_number", "")), _normalise_section(chunk.get("section_number"))): chunk
        for chunk in state.get("retrieved_chunks", [])
    }
    seen_evidence: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    try:
        max_quote_chars = min(500, max(1, int(os.getenv("RECEIPT_EVIDENCE_MAX_CHARS", "500"))))
    except ValueError:
        logger.warning("Invalid RECEIPT_EVIDENCE_MAX_CHARS; using 500")
        max_quote_chars = 500

    for claim in result.claims:
        if claim.support == "unsupported":
            msg = (
                "Grounding check failed: "
                f"unsupported claim citing Section {claim.cited_section_number} "
                f"of Act {claim.cited_act_number}: {claim.reason}"
            )
            violations.append(msg)
            evidence_violations.append(msg)
        if claim.support != "supported":
            continue

        key = (str(claim.cited_act_number), _normalise_section(claim.cited_section_number))
        citation = citation_lookup.get(key)
        chunk = chunk_lookup.get(key)
        receipt = citation.get("receipt") if citation else None
        quote = claim.quote.strip()
        if (
            not citation
            or not chunk
            or not isinstance(receipt, dict)
            or not quote
            or len(quote) > max_quote_chars
            or not contains_normalized_sequence(claim.claim, state.get("draft_response", ""))
            or not contains_normalized_sequence(quote, chunk.get("content", ""))
        ):
            continue

        fingerprint = (tuple(normalized_tokens(claim.claim)), tuple(normalized_tokens(quote)))
        if fingerprint in seen_evidence:
            continue
        seen_evidence.add(fingerprint)
        receipt.setdefault("evidence", []).append({"claim": claim.claim.strip(), "quote": quote})

    return {
        "violations": violations,
        "evidence_violations": evidence_violations,
        "citations": citations,
    }


def grounding_check_node(state: AgentState) -> dict:
    violations = list(state.get("violations", []))
    # If deterministic citation validation already failed, avoid an extra LLM call;
    # the retry loop should first produce structurally valid citations.
    if violations:
        return {"violations": violations}

    answer = state.get("draft_response", "")
    sources = _collect_cited_sources(state)
    if not answer or not sources:
        return {"violations": violations}

    try:
        result: _GroundingOutput = _grounding_llm.invoke(_messages(answer, sources))
    except Exception:
        # The judge malfunctioning is not evidence that the answer is ungrounded.
        # Fail open: citation validation already guaranteed structural integrity, so
        # a transient extraction error should not discard an otherwise valid answer.
        logger.warning("grounding_check_node failed; skipping grounding verification", exc_info=True)
        return {"violations": violations}
    return _finalise(result, state, violations)


async def agrounding_check_node(state: AgentState) -> dict:
    violations = list(state.get("violations", []))
    if violations:
        return {"violations": violations}

    answer = state.get("draft_response", "")
    sources = _collect_cited_sources(state)
    if not answer or not sources:
        return {"violations": violations}

    try:
        result: _GroundingOutput = await _grounding_llm.ainvoke(_messages(answer, sources))
    except Exception:
        logger.warning("grounding_check_node failed; skipping grounding verification", exc_info=True)
        return {"violations": violations}
    return _finalise(result, state, violations)
