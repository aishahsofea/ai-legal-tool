"""
Synthesiser node — drafts a response grounded in retrieved chunks with structured citations.

Responds in the dominant language of the query (EN or BM).
Cited text always uses the English statute text regardless of query language.
"""
import json
from typing import Optional

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from agent.state import AgentState

load_dotenv()

_llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)


class _CitationRef(BaseModel):
    act_number: str
    section_number: str


class _SynthesiserOutput(BaseModel):
    answer: str
    citation_refs: list[_CitationRef]  # Claude only names sections; URLs come from retrieved chunks


_structured_llm = _llm.with_structured_output(_SynthesiserOutput)

_SYSTEM = """You are a Malaysian legal research assistant. Your role is to answer research questions about Malaysian legislation by citing the relevant statute sections.

Rules you MUST follow on every response:
1. Every legal claim must cite "Section X of [Act Title]" explicitly.
2. End every response with this exact disclaimer: "This information is for legal research only and does not constitute legal advice. Please consult a qualified Malaysian lawyer for advice on your specific situation."
3. Do NOT use phrases like "you should", "you must", "in your case", or "I recommend".
4. Only state what the statute says — do not advise on what a person should do.
5. Respond in the same language as the user's query (English or Bahasa Malaysia). If mixed, default to English.
6. If the retrieved sections do not contain enough information to answer, say so clearly rather than speculating."""


def synthesiser_node(state: AgentState) -> dict:
    chunks = state["retrieved_chunks"]

    context = "\n\n".join(
        f"[Section {c['section_number']}, {c['act_title']} (Act {c['act_number']})]\n{c['content']}"
        for c in chunks
    )

    user_message = f"""Query: {state['query']}

Retrieved statute sections:
{context}

Answer the query using only the sections provided above. Cite each section you rely on."""

    result: _SynthesiserOutput = _structured_llm.invoke([
        {"role": "system", "content": _SYSTEM},
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

    disclaimer = (
        "\n\n---\n"
        "*This information is for legal research only and does not constitute legal advice. "
        "Please consult a qualified Malaysian lawyer for advice on your specific situation.*"
    )
    answer_with_disclaimer = result.answer.rstrip() + disclaimer

    return {
        "draft_response": answer_with_disclaimer,
        "citations":      citations,
    }
