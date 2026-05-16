"""Span-level grounding check for generated legal answers.

This node asks an LLM judge to verify whether legal claims in the draft answer are
supported by the cited retrieved statute sections. It intentionally runs after
citation validation, so it can assume citation references are structurally sane.
"""
from __future__ import annotations

import json
from typing import Literal

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from agent.state import AgentState

load_dotenv()

_llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


class _GroundingClaim(BaseModel):
    claim: str = Field(description="A sentence or clause from the answer that makes a legal claim.")
    cited_act_number: str = Field(description="Act number used to support the claim.")
    cited_section_number: str = Field(description="Section number used to support the claim.")
    support: Literal["supported", "partial", "unsupported"]
    reason: str


class _GroundingOutput(BaseModel):
    claims: list[_GroundingClaim]


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

    payload = {
        "answer": answer,
        "cited_sources": sources,
    }

    try:
        result: _GroundingOutput = _grounding_llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ])
    except Exception as exc:
        violations.append(f"Grounding check failed: {exc}")
        return {"violations": violations}

    for claim in result.claims:
        if claim.support == "unsupported":
            violations.append(
                "Grounding check failed: "
                f"unsupported claim citing Section {claim.cited_section_number} "
                f"of Act {claim.cited_act_number}: {claim.reason}"
            )

    return {"violations": violations}
