"""
Retriever node — embeds the query and searches pgvector for the top-k chunks.

Searches both English chunks (cross-lingual embedding handles BM and mixed queries).
Attaches the AGC PDF URL (with page anchor) to each chunk for citation deep links.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI

from agent.state import AgentState

load_dotenv()

TOP_K        = 8
EXACT_TOP_K  = 3
METADATA_DIR = Path("data/acts_metadata")

_SECTION_RE = re.compile(r"\b(?:section|sec\.?|s\.?)\s*(\d+[A-Z]{0,2})\b", re.IGNORECASE)
_ACT_NUMBER_RE = re.compile(r"\bact\s+(\d+[A-Z]?)\b", re.IGNORECASE)
_ACT_ALIASES: dict[str, tuple[str, str]] = {
    "evidence act": ("56", "EVIDENCE ACT 1950"),
    "penal code": ("574", "PENAL CODE"),
    "criminal procedure code": ("593", "CRIMINAL PROCEDURE CODE"),
    "cpc": ("593", "CRIMINAL PROCEDURE CODE"),
    "employment act": ("265", "EMPLOYMENT ACT 1955"),
    "companies act": ("777", "COMPANIES ACT 2016"),
    "pdpa": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
    "personal data protection act": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
}

_openai  = OpenAI()
_db_url  = os.environ["DATABASE_URL"]


@lru_cache(maxsize=1)
def _pdf_url_map() -> dict[str, str]:
    """Build {act_number: latest_reprint_pdf} from metadata files. Cached on first call."""
    result = {}
    for f in METADATA_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            url = d.get("latest_reprint_pdf") or d.get("latest_amendment_pdf") or ""
            result[d["act_number"]] = url
        except Exception:
            pass
    return result


def _embed(text: str) -> list[float]:
    resp = _openai.embeddings.create(model="text-embedding-3-small", input=[text])
    return resp.data[0].embedding


def _extract_section_number(query: str) -> str | None:
    match = _SECTION_RE.search(query)
    return match.group(1).upper() if match else None


def _extract_act_hint(query: str) -> tuple[str | None, str | None]:
    lowered = query.lower()
    for alias, act in _ACT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return act

    act_number = _ACT_NUMBER_RE.search(query)
    if act_number:
        return act_number.group(1).upper(), None
    return None, None


def _attach_pdf_urls(rows: list[dict]) -> list[dict]:
    pdf_map = _pdf_url_map()
    chunks = []
    for row in rows:
        d = dict(row)
        base_url = pdf_map.get(d["act_number"], "")
        d["pdf_url"] = f"{base_url}#page={d['page_number']}" if base_url and d.get("page_number") else base_url
        chunks.append(d)
    return chunks


def _exact_statute_lookup(conn, query: str) -> list[dict]:
    section_number = _extract_section_number(query)
    act_number, act_title = _extract_act_hint(query)
    if not section_number or not (act_number or act_title):
        return []

    title_pattern = f"%{act_title}%" if act_title else ""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT act_number, act_title, section_number, content, page_number, language,
                   1.0 AS similarity
            FROM chunks
            WHERE UPPER(section_number) = %s
              AND (act_number = %s OR act_title ILIKE %s)
            ORDER BY
              CASE WHEN act_number = %s THEN 0 ELSE 1 END,
              CASE WHEN language = 'en' THEN 0 ELSE 1 END
            LIMIT %s
            """,
            (section_number, act_number or "", title_pattern, act_number or "", EXACT_TOP_K),
        )
        return [dict(row) for row in cur.fetchall()]


def _vector_search(conn, query: str) -> list[dict]:
    query_vec = _embed(query)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT act_number, act_title, section_number, content, page_number, language,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_vec, query_vec, TOP_K),
        )
        return [dict(row) for row in cur.fetchall()]


def retriever_node(state: AgentState) -> dict:
    conn = psycopg2.connect(_db_url)
    try:
        rows = []
        if state.get("query_type") == "statute_lookup":
            rows = _exact_statute_lookup(conn, state["query"])
        if not rows:
            rows = _vector_search(conn, state["query"])
    finally:
        conn.close()

    return {"retrieved_chunks": _attach_pdf_urls(rows)}
