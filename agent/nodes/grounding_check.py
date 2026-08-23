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

from agent.citation_keys import canonicalize_citation_key
from agent.llm_factory import make_llm, system_content
from agent.state import AgentState
from citation_receipts.locator import contains_normalized_sequence, normalized_tokens

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = os.getenv("GROUNDING_MODEL", "claude-sonnet-4-6")
_llm = make_llm(_MODEL)


class _GroundingClaim(BaseModel):
    # Field order is the fill order for structured output: quote and reason are declared
    # before support so the judge finds the passage before it picks a label.
    claim: str = Field(description="A sentence or clause from the answer that makes a legal claim.")
    cited_act_number: str = Field(description="Act number used to support the claim.")
    cited_section_number: str = Field(description="Section number used to support the claim.")
    quote: str = Field(
        default="",
        description=(
            "The best short contiguous verbatim passage from the cited source that carries "
            "this claim, or empty when the source contains none."
        ),
    )
    reason: str
    support: Literal["supported", "partial", "unsupported"]


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
- For each legal claim, find the passage in the cited statute section text that carries
  it, then label how far that passage goes.
- Use only the provided cited source text. Do not use outside legal knowledge.

Labels:
- supported: the cited section text directly supports the claim.
- partial: the cited section text supports only part of the claim or the claim overstates the text.
- unsupported: the cited section text does not support the claim.

Work each claim in this order, and fill the fields in this order:
1. quote: copy the best passage from the cited source text that carries the claim — one
   short, contiguous, verbatim passage. Do not paraphrase, splice passages, or add
   ellipses. Leave quote empty when the cited text holds no such passage.
2. reason: say what the quote does and does not cover.
3. support: label the claim. Only use "supported" when quote holds a real passage that
   carries the whole claim.

Deciding the label from the passage you found is the point of this order. Do not pick a
label first and then look for a quote that fits it.

Ignore non-legal text such as disclaimers, transitions, headings, and source labels.
Return only the structured result."""

def _collect_cited_sources(state: AgentState) -> list[dict]:
    sources = []
    seen = set()
    for citation in state.get("citations", []):
        key = canonicalize_citation_key(
            citation.get("act_number"),
            citation.get("section_number"),
        )
        receipt = citation.get("receipt") if isinstance(citation.get("receipt"), dict) else {}
        document_id = receipt.get("document_id") if receipt else None
        source_key = (*key, document_id or "")
        if source_key in seen:
            continue
        seen.add(source_key)
        candidates = [
            chunk for chunk in state.get("retrieved_chunks", [])
            if canonicalize_citation_key(
                chunk.get("act_number"), chunk.get("section_number")
            ) == key
            and (not document_id or chunk.get("document_id") == document_id)
        ]
        chunk = candidates[0] if candidates else None
        if not chunk:
            continue
        sources.append({
            "act_number": chunk.get("act_number", ""),
            "act_title": chunk.get("act_title", ""),
            "section_number": chunk.get("section_number", ""),
            "content": chunk.get("content", ""),
            "document_id": chunk.get("document_id", ""),
            "extraction_id": chunk.get("extraction_id", ""),
        })
    return sources


def _messages(answer: str, sources: list[dict]) -> list[dict]:
    # Sources before answer, which is the reverse of this function's own argument order:
    # the section text is the long block and the judged answer belongs last.
    payload = {"cited_sources": sources, "answer": answer}
    return [
        {"role": "system", "content": system_content(_SYSTEM, _MODEL)},
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
    # The judge may return display-form identifiers (for example, ``Act 56`` and
    # ``Section 90A(1)``), while receipts retain the retrieved bare identifiers.
    # Use the shared key at this final comparison boundary as well as source lookup.
    citation_lookup: dict[tuple[str, str], list[dict]] = {}
    chunk_lookup: dict[tuple[str, str], list[dict]] = {}
    for citation in citations:
        key = canonicalize_citation_key(citation.get("act_number"), citation.get("section_number"))
        citation_lookup.setdefault(key, []).append(citation)
    for chunk in state.get("retrieved_chunks", []):
        key = canonicalize_citation_key(chunk.get("act_number"), chunk.get("section_number"))
        chunk_lookup.setdefault(key, []).append(chunk)
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

        key = canonicalize_citation_key(
            claim.cited_act_number,
            claim.cited_section_number,
        )
        citation_candidates = citation_lookup.get(key, [])
        citation = citation_candidates[0] if citation_candidates else None
        receipt_identity = (
            citation.get("receipt", {}).get("document_id")
            if citation and isinstance(citation.get("receipt"), dict)
            else None
        )
        chunk_candidates = chunk_lookup.get(key, [])
        chunk = next(
            (item for item in chunk_candidates if receipt_identity and item.get("document_id") == receipt_identity),
            chunk_candidates[0] if not receipt_identity and chunk_candidates else None,
        )
        receipt = citation.get("receipt") if citation else None
        quote = claim.quote.strip()
        if (
            not citation
            or not chunk
            or not isinstance(receipt, dict)
            or chunk.get("document_id") != receipt.get("document_id")
            or chunk.get("extraction_id") != receipt.get("extraction_id")
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
