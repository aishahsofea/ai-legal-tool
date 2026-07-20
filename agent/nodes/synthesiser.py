"""
Synthesiser node — drafts a response grounded in retrieved chunks with structured citations.

Responds in the dominant language of the query (EN or BM).
Cited text retains the registered language of the retrieved statute source.
"""
import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from agent.citation_keys import canonicalize_citation_key
from agent.llm_factory import make_llm, system_content
from agent.query_policy import _DISCLAIMER_BM, _DISCLAIMER_EN, trim_history
from agent.state import AgentState
from citation_receipts import ReceiptDocumentIntegrityError, ReceiptManifestError, get_receipt_registry
from citation_receipts.service import validate_available, validate_coordinate_available

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = os.getenv("SYNTHESISER_MODEL", "gpt-4.1")
_llm = make_llm(_MODEL)


class _CitationRef(BaseModel):
    act_number: str
    section_number: str


class _SynthesiserOutput(BaseModel):
    answer: str
    citation_refs: list[_CitationRef]  # Claude only names sections; URLs come from retrieved chunks


_structured_llm = _llm.with_structured_output(_SynthesiserOutput)

_SYSTEM_TEMPLATE = """You are a Malaysian legal research assistant. Your role is to answer research questions about Malaysian legislation by citing the relevant statute sections.

Write like a knowledgeable, plain-spoken colleague: clear and natural, not robotic. Vary your phrasing from answer to answer — never open every response with the same fixed stem.

Rules you MUST follow on every response:
1. LANGUAGE: You MUST respond in {language_instruction}. This rule overrides everything else.
2. Every legal claim must cite the relevant section explicitly.
3. Do NOT use phrases like "you should", "you must", "in your case", or "I recommend".
4. Only state what the statute says — do not advise on what a person should do.
5. If the retrieved sections do not contain enough information to answer, say so clearly rather than speculating.
6. Omit the disclaimer from your answer field — it will be appended separately.
7. In citation_refs, include an entry for EVERY section you mention in your answer. If you mention section 90A(1) and 90A(2), add one entry with section_number "90A". Never leave citation_refs empty if your answer cites any section.
8. Any "Known practitioner preferences" are soft context about how this practitioner likes answers framed (language, format, focus). They are NOT legal authority: never cite them, never treat them as facts about the law, and let the retrieved sections and the query override them whenever they conflict."""

_LANGUAGE_INSTRUCTIONS = {
    "en": "English",
    "bm": (
        "Bahasa Malaysia throughout. Quote statute text in the exact language of the retrieved source; "
        "do not translate or relabel a BM-only source as English"
    ),
    "mixed": (
        "a bilingual format: write the explanation and framing in Bahasa Malaysia, "
        "and keep embedded statute quotations in the exact language of each retrieved source"
    ),
}


def _build_messages(state: AgentState) -> list[dict]:
    chunks = state["retrieved_chunks"]
    history = trim_history(state.get("history", []))
    response_language = state.get("response_language", "en")
    recalled_memory = state.get("recalled_memory", "")

    context = "\n\n".join(
        f"[Section {c['section_number']}, {c['act_title']} (Act {c['act_number']}), source language: {c.get('language', 'unknown')}]\n{c['content']}"
        for c in chunks
    )
    history_text = "\n\n".join(
        f"{turn['role'].title()}: {turn['content']}" for turn in history
    )

    system_prompt = _SYSTEM_TEMPLATE.format(
        language_instruction=_LANGUAGE_INSTRUCTIONS.get(response_language, _LANGUAGE_INSTRUCTIONS["en"])
    )

    preferences_block = (
        f"\nKnown practitioner preferences (framing only, not legal authority):\n{recalled_memory}\n"
        if recalled_memory
        else ""
    )

    user_message = f"""Conversation history:
{history_text or '(none)'}
{preferences_block}
Query: {state['query']}

Retrieved statute sections:
{context}

Answer the query using only the sections provided above. Cite each section you rely on."""

    return [
        {"role": "system", "content": system_content(system_prompt, _MODEL)},
        {"role": "user", "content": user_message},
    ]


def _finalise(result: _SynthesiserOutput, state: AgentState) -> dict:
    chunks = state["retrieved_chunks"]
    response_language = state.get("response_language", "en")

    # LLMs may echo display labels ("Act 559") while the database stores bare
    # identifiers ("559"). Canonical keys prevent valid citations from being
    # silently dropped; output metadata still comes from the retrieved chunk.
    chunk_lookup: dict[tuple[str, str], dict] = {}
    for chunk in chunks:
        key = canonicalize_citation_key(
            chunk.get("act_number"),
            chunk.get("section_number"),
        )
        if all(key):
            # Retrieval is already ordered by relevance. Preserve the first exact
            # provenance row instead of allowing another language/version to replace it.
            chunk_lookup.setdefault(key, chunk)

    citations = []
    for ref in result.citation_refs:
        ref_key = canonicalize_citation_key(ref.act_number, ref.section_number)
        chunk = chunk_lookup.get(ref_key)
        if chunk:
            citation = {
                "act_number":     chunk["act_number"],
                "act_title":      chunk["act_title"],
                "section_number": chunk["section_number"],
                "pdf_url":        chunk.get("pdf_url", ""),
                "page_number":    chunk.get("page_number"),
            }
            document_id = chunk.get("document_id")
            extraction_id = chunk.get("extraction_id")
            receipt_document = None
            if document_id and extraction_id:
                try:
                    registry = get_receipt_registry()
                    receipt_document = registry.get(document_id)
                    if (
                        receipt_document.act_number != str(chunk.get("act_number", ""))
                        or receipt_document.language != str(chunk.get("language", ""))
                    ):
                        raise ReceiptDocumentIntegrityError("Chunk/document metadata mismatch")
                    extraction = registry.validate_exact_extraction(receipt_document, extraction_id)
                    validate_available(registry, receipt_document)
                    validate_coordinate_available(registry, extraction)
                except (ReceiptManifestError, ReceiptDocumentIntegrityError, KeyError):
                    logger.warning(
                        "Exact Receipt provenance unavailable; retaining official source only",
                        extra={"document_id": document_id, "extraction_id": extraction_id},
                    )
                    receipt_document = None
            if receipt_document is not None:
                citation["receipt"] = {
                    "document_id": receipt_document.document_id,
                    "extraction_id": extraction_id,
                    "evidence": [],
                }
            citations.append(citation)

    disclaimer = _DISCLAIMER_BM if response_language in ("bm", "mixed") else _DISCLAIMER_EN
    answer_with_disclaimer = result.answer.rstrip() + disclaimer

    return {
        "draft_response": answer_with_disclaimer,
        "citations":      citations,
    }


def synthesiser_node(state: AgentState) -> dict:
    result: _SynthesiserOutput = _structured_llm.invoke(_build_messages(state))
    return _finalise(result, state)


async def asynthesiser_node(state: AgentState) -> dict:
    result: _SynthesiserOutput = await _structured_llm.ainvoke(_build_messages(state))
    return _finalise(result, state)
