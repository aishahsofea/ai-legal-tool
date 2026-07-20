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
    """Build official base-Act links from reprints only.

    Amendment-only PDFs are never valid substitutes for a base Act.
    """
    result = {}
    for f in METADATA_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            url = d.get("latest_reprint_pdf") or ""
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
    """Attach the exact registered source URL, or a legacy official reprint link."""
    pdf_map = _pdf_url_map()
    chunks = []
    for row in rows:
        d = dict(row)
        base_url = d.pop("source_url", "") if d.get("document_id") else ""
        base_url = base_url or pdf_map.get(d["act_number"], "")
        page = d.get("page_start") or d.get("page_number")
        d["pdf_url"] = f"{base_url}#page={page}" if base_url and page else base_url
        chunks.append(d)
    return chunks


def _retrieval_mode() -> str:
    mode = os.getenv("CORPUS_RETRIEVAL_MODE", "dual").strip().lower()
    return mode if mode in {"legacy", "dual", "verified"} else "dual"


def _has_provenance_schema(cur) -> bool:
    """Return whether the additive corpus migration is available on this database.

    Dual-read must work both before and after the migration. Detecting the table
    and nullable chunk column lets retrieval choose a compatible query without
    guessing provenance for legacy rows or requiring a flag-day deployment.
    """
    cur.execute(
        """
        SELECT (
          to_regclass('public.active_corpus_documents') IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'chunks'
              AND column_name = 'document_id'
          )
        ) AS available
        """
    )
    row = cur.fetchone()
    return bool(row and row["available"])


def _select_columns(provenance: bool) -> str:
    if not provenance:
        return (
            "act_number, act_title, section_number, content, page_number, language, "
            "NULL::text AS document_id, NULL::text AS extraction_id, "
            "NULL::text AS content_sha256, page_number AS page_start, "
            "page_number AS page_end, NULL::text AS source_url"
        )
    return (
        "c.act_number, c.act_title, c.section_number, c.content, c.page_number, c.language, "
        "c.document_id, c.extraction_id, c.content_sha256, "
        "COALESCE(c.page_start, c.page_number) AS page_start, "
        "COALESCE(c.page_end, c.page_number) AS page_end, d.source_url"
    )


def _provenance_visibility(mode: str) -> str:
    if mode == "verified":
        return "c.document_id IS NOT NULL AND a.document_id IS NOT NULL"
    if mode == "legacy":
        return "c.document_id IS NULL"
    # During dual-read, an activated exact extraction owns its Act/language.
    # Legacy rows remain a fallback only where no verified mapping is active.
    return """(
        a.document_id IS NOT NULL
        OR (
          c.document_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM active_corpus_documents current
            WHERE current.act_number = c.act_number
              AND current.language = c.language
          )
        )
    )"""


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
            # trade-off for the current corpus size.
            cur.execute("SET ivfflat.probes = 10;")
            mode = _retrieval_mode()
            provenance = _has_provenance_schema(cur)
            if mode == "verified" and not provenance:
                return []
            prefix = "c." if provenance else ""
            joins = """
                LEFT JOIN active_corpus_documents a
                  ON a.act_number = c.act_number AND a.language = c.language
                 AND a.document_id = c.document_id AND a.extraction_id = c.extraction_id
                LEFT JOIN corpus_documents d ON d.document_id = c.document_id
            """ if provenance else ""
            provenance_filter = _provenance_visibility(mode) if provenance else ""
            combined_filters = [f"c.{item}" for item in filters] if provenance else list(filters)
            if provenance_filter:
                combined_filters.append(provenance_filter)
            where = f"WHERE {' AND '.join(combined_filters)}" if combined_filters else ""
            cur.execute(
                f"""
                SELECT {_select_columns(provenance)},
                       1 - ({prefix}embedding <=> %s::vector) AS similarity
                FROM chunks {prefix.rstrip('.')}
                {joins}
                {where}
                ORDER BY {prefix}embedding <=> %s::vector
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
            mode = _retrieval_mode()
            provenance = _has_provenance_schema(cur)
            if mode == "verified" and not provenance:
                return []
            joins = """
                LEFT JOIN active_corpus_documents a
                  ON a.act_number = c.act_number AND a.language = c.language
                 AND a.document_id = c.document_id AND a.extraction_id = c.extraction_id
                LEFT JOIN corpus_documents d ON d.document_id = c.document_id
            """ if provenance else ""
            provenance_filter = f"AND {_provenance_visibility(mode)}" if provenance else ""
            prefix = "c." if provenance else ""
            cur.execute(
                f"""
                SELECT {_select_columns(provenance)},
                       1.0 AS similarity
                FROM chunks {prefix.rstrip('.')}
                {joins}
                WHERE UPPER({prefix}section_number) = %s
                  AND ({prefix}act_number = %s OR {prefix}act_title ILIKE %s)
                  {provenance_filter}
                ORDER BY
                  CASE WHEN {prefix}act_number = %s THEN 0 ELSE 1 END,
                  CASE WHEN {prefix}language = 'en' THEN 0 ELSE 1 END
                LIMIT %s
                """,
                (section_number, act_number or "", title_pattern, act_number or "", EXACT_TOP_K),
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    return attach_pdf_urls(rows)
