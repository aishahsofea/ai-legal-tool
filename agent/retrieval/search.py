"""
Statute search layer — pgvector semantic search and exact section lookup.

Extracted from the retriever node so the same functions can back both the
deterministic node and the agentic retrieval tools (agent/retrieval/tools.py).
Each function owns its own psycopg2 connection so callers don't have to thread
one through; the return shape is the chunk dict the rest of the graph already
expects (act_number, act_title, section_number, content, page_number, language,
similarity, pdf_url).
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

load_dotenv()

TOP_K        = 8
EXACT_TOP_K  = 3
METADATA_DIR = Path("data/acts_metadata")

_SECTION_RE = re.compile(r"\b(?:seksyen|sek\.?|section|sec\.?|s\.?)\s*(\d+[A-Z]{0,2})\b", re.IGNORECASE)
_ACT_NUMBER_RE = re.compile(r"\bact\s+(\d+[A-Z]?)\b", re.IGNORECASE)
_ACT_ALIASES: dict[str, tuple[str, str]] = {
    "evidence act": ("56", "EVIDENCE ACT 1950"),
    "akta keterangan": ("56", "EVIDENCE ACT 1950"),
    "penal code": ("574", "PENAL CODE"),
    "kanun keseksaan": ("574", "PENAL CODE"),
    "criminal procedure code": ("593", "CRIMINAL PROCEDURE CODE"),
    "cpc": ("593", "CRIMINAL PROCEDURE CODE"),
    "employment act": ("265", "EMPLOYMENT ACT 1955"),
    "akta pekerjaan": ("265", "EMPLOYMENT ACT 1955"),
    "companies act": ("777", "COMPANIES ACT 2016"),
    "akta syarikat": ("777", "COMPANIES ACT 2016"),
    "pdpa": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
    "akta pdpa": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
    "personal data protection act": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
    "akta perlindungan data peribadi": ("709", "PERSONAL DATA PROTECTION ACT 2010"),
}

_openai = OpenAI()
_db_url = os.environ["DATABASE_URL"]


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


def extract_section_number(query: str) -> str | None:
    """Pull a section number (e.g. '90A') out of free text, or None."""
    match = _SECTION_RE.search(query)
    return match.group(1).upper() if match else None


def extract_act_hint(query: str) -> tuple[str | None, str | None]:
    """Resolve an Act reference in free text to (act_number, act_title).

    Matches a known alias ('evidence act' → ('56', 'EVIDENCE ACT 1950')) first,
    then a bare 'Act <number>'. Returns (None, None) when nothing matches.
    """
    lowered = query.lower()
    for alias, act in _ACT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return act

    act_number = _ACT_NUMBER_RE.search(query)
    if act_number:
        return act_number.group(1).upper(), None
    return None, None


def attach_pdf_urls(rows: list[dict]) -> list[dict]:
    """Add a `pdf_url` (base + #page anchor) to each chunk from Act metadata."""
    pdf_map = _pdf_url_map()
    chunks = []
    for row in rows:
        d = dict(row)
        base_url = pdf_map.get(d["act_number"], "")
        d["pdf_url"] = f"{base_url}#page={d['page_number']}" if base_url and d.get("page_number") else base_url
        chunks.append(d)
    return chunks


def semantic_search(
    query: str,
    top_k: int = TOP_K,
    act_number: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Cosine-similarity search over the pgvector `chunks` table.

    Optional `act_number` / `language` narrow the search; both None searches the
    whole corpus (the cross-lingual embedding handles BM/mixed queries either way).
    Returns chunk dicts with `pdf_url` attached, most similar first.
    """
    query_vec = _embed(query)
    filters = []
    params: list = [query_vec]
    if act_number:
        filters.append("act_number = %s")
        params.append(act_number)
    if language:
        filters.append("language = %s")
        params.append(language)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.extend([query_vec, top_k])

    conn = psycopg2.connect(_db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Increase ivfflat probes from default 1 → 10 for better recall.
            # Default probes=1 misses correct clusters; 10 is a good recall/speed
            # trade-off for a pilot corpus of ~24k chunks.
            cur.execute("SET ivfflat.probes = 10;")
            cur.execute(
                f"""
                SELECT act_number, act_title, section_number, content, page_number, language,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM chunks
                {where}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                params,
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    return attach_pdf_urls(rows)


def exact_section_lookup(
    section: str,
    act_number: str | None = None,
    act_title: str | None = None,
) -> list[dict]:
    """Exact match on a section number within a specific Act (no embedding call).

    Needs a section plus at least one Act hint (`act_number` or `act_title`);
    returns [] otherwise so callers can fall back to semantic search. English
    chunks and the exact-act match are ordered first.
    """
    section_number = extract_section_number(section) or (section or "").strip().upper()
    if not section_number or not (act_number or act_title):
        return []

    title_pattern = f"%{act_title}%" if act_title else ""
    conn = psycopg2.connect(_db_url)
    try:
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
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    return attach_pdf_urls(rows)
