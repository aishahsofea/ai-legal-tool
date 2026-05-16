"""
Synthesiser node — drafts a response grounded in retrieved chunks with structured citations.

Responds in the dominant language of the query (EN or BM).
Cited text always uses the English statute text regardless of query language.
"""
import json
import os
from typing import Optional

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from agent.state import AgentState

load_dotenv()

_llm = ChatAnthropic(model=os.getenv("SYNTHESISER_MODEL", "claude-sonnet-4-6"), temperature=0)


class _CitationRef(BaseModel):
    act_number: str
    section_number: str


class _SynthesiserOutput(BaseModel):
    answer: str
    citation_refs: list[_CitationRef]  # Claude only names sections; URLs come from retrieved chunks


_structured_llm = _llm.with_structured_output(_SynthesiserOutput)

_DISCLAIMER_EN = (
    "\n\n---\n"
    "*This information is for legal research only and does not constitute legal advice. "
    "Please consult a qualified Malaysian lawyer for advice on your specific situation.*"
)
_DISCLAIMER_BM = (
    "\n\n---\n"
    "*Maklumat ini adalah untuk tujuan penyelidikan undang-undang sahaja dan tidak merupakan "
    "nasihat undang-undang. Sila rujuk peguam Malaysia yang berkelayakan untuk nasihat berhubung "
    "situasi khusus anda.*"
)

_SYSTEM_TEMPLATE = """You are a Malaysian legal research assistant. Your role is to answer research questions about Malaysian legislation by citing the relevant statute sections.

Rules you MUST follow on every response:
1. LANGUAGE: You MUST respond in {language_instruction}. This rule overrides everything else.
2. Every legal claim must cite the relevant section explicitly.
3. Do NOT use phrases like "you should", "you must", "in your case", or "I recommend".
4. Only state what the statute says — do not advise on what a person should do.
5. If the retrieved sections do not contain enough information to answer, say so clearly rather than speculating.
6. Omit the disclaimer from your answer field — it will be appended separately.
7. In citation_refs, include an entry for EVERY section you mention in your answer. If you mention section 90A(1) and 90A(2), add one entry with section_number "90A". Never leave citation_refs empty if your answer cites any section."""

_LANGUAGE_INSTRUCTIONS = {
    "en": "English",
    "bm": (
        "Bahasa Malaysia throughout. Quote English statute text inline when citing a section "
        "(e.g. \"Di bawah seksyen 60A Akta Pekerjaan 1955, *'No employee shall be required...'*\") "
        "— the quoted statute text may remain in English as it is the authoritative court version"
    ),
    "mixed": (
        "a bilingual format: write the explanation and framing in Bahasa Malaysia, "
        "and embed English statute quotations inline when citing sections. "
        "The statute quotations may remain in English as they are the authoritative court version"
    ),
}


def synthesiser_node(state: AgentState) -> dict:
    chunks = state["retrieved_chunks"]
    history = state.get("history", [])
    response_language = state.get("response_language", "en")

    context = "\n\n".join(
        f"[Section {c['section_number']}, {c['act_title']} (Act {c['act_number']})]\n{c['content']}"
        for c in chunks
    )
    history_text = "\n\n".join(
        f"{turn['role'].title()}: {turn['content']}" for turn in history
    )

    system_prompt = _SYSTEM_TEMPLATE.format(
        language_instruction=_LANGUAGE_INSTRUCTIONS.get(response_language, _LANGUAGE_INSTRUCTIONS["en"])
    )

    user_message = f"""Conversation history:
{history_text or '(none)'}

Query: {state['query']}

Retrieved statute sections:
{context}

Answer the query using only the sections provided above. Cite each section you rely on."""

    result: _SynthesiserOutput = _structured_llm.invoke([
        {"role": "system", "content": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": user_message},
    ])

    # Build a lookup from retrieved chunks so URLs come from the database, not Claude.
    chunk_lookup: dict[tuple, dict] = {
        (c["act_number"], c["section_number"]): c
        for c in chunks
    }

    citations = []
    for ref in result.citation_refs:
        chunk = chunk_lookup.get((ref.act_number, ref.section_number))
        if chunk:
            citations.append({
                "act_number":     chunk["act_number"],
                "act_title":      chunk["act_title"],
                "section_number": chunk["section_number"],
                "pdf_url":        chunk.get("pdf_url", ""),
                "page_number":    chunk.get("page_number"),
            })

    disclaimer = _DISCLAIMER_BM if response_language in ("bm", "mixed") else _DISCLAIMER_EN
    answer_with_disclaimer = result.answer.rstrip() + disclaimer

    return {
        "draft_response": answer_with_disclaimer,
        "citations":      citations,
    }
