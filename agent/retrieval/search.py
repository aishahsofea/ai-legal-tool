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

from agent.citation_keys import canonicalize_path
from agent.embeddings import make_corpus_embedder

load_dotenv()

TOP_K        = 8
EXACT_TOP_K  = 3
METADATA_DIR = Path("data/acts_metadata")
ACTS_MANIFEST_PATH = Path("data/pdfs/manifest.json")

_SECTION_RE = re.compile(r"\b(?:seksyen|sek\.?|section|sec\.?|s\.?)\s*(\d+[A-Z]{0,2})\b", re.IGNORECASE)
_ACT_NUMBER_RE = re.compile(r"\bact\s+(\d+[A-Z]?)\b", re.IGNORECASE)
_ACT_TEXT_RE = re.compile(r"[^a-z0-9]+")
_ACT_YEAR_SUFFIX_RE = re.compile(r"\s(?:18|19|20)\d{2}$")

# Names ACTS_MANIFEST_PATH can't supply: an abbreviation (no title spells out
# "CPC"/"PDPA"/"SPRM"), or a language with no title registered for that Act
# at all - the manifest has no Malay document for the Penal Code, the
# Employment Act, or the Criminal Procedure Code (issue #62).
_ACT_ALIASES: dict[str, str] = {
    "cpc": "593",
    "kanun tatacara jenayah": "593",
    "pdpa": "709",
    "kanun keseksaan": "574",
    "akta pekerjaan": "265",
    "sprm": "694",
}

_openai, _EMBED_MODEL = make_corpus_embedder()
_db_url = os.environ["DATABASE_URL"]


def get_connection():
    """Open a connection callers can share across several lookups in one request."""
    return psycopg2.connect(_db_url)


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
    resp = _openai.embeddings.create(model=_EMBED_MODEL, input=[text])
    return resp.data[0].embedding


def extract_section_number(query: str) -> str | None:
    """Pull a section number (e.g. '90A') out of free text, or None."""
    match = _SECTION_RE.search(query)
    return match.group(1).upper() if match else None


def _normalize_act_text(text: str) -> str:
    """Fold to lowercase and collapse punctuation to single spaces, dropping
    the manifest's leading '*' marker, so title matching ignores casing and
    punctuation (issue #62)."""
    text = text.strip()
    if text.startswith("*"):
        text = text[1:]
    return _ACT_TEXT_RE.sub(" ", text.lower()).strip()


def _bare_act_title(title: str) -> str:
    """Normalized title with a trailing year dropped, e.g. 'evidence act' for
    'EVIDENCE ACT 1950'. Most real references to an Act omit the year, and a
    query that does include it still contains this shorter form too."""
    return _ACT_YEAR_SUFFIX_RE.sub("", _normalize_act_text(title))


@lru_cache(maxsize=1)
def _act_title_index() -> tuple[list[tuple[str, str, str | None]], dict[str, str]]:
    """Build the Act-title match pool from ACTS_MANIFEST_PATH, plus a per-Act
    fallback display title for `_ACT_ALIASES` entries.

    Cached for the process lifetime, like `_pdf_url_map` - extract_act_hint
    runs on every query, and the manifest holds over a thousand documents.
    Each pool entry is (act_number, bare normalized title, display title);
    `_ACT_ALIASES` entries carry no title of their own, so theirs is None.
    """
    pool: list[tuple[str, str, str | None]] = []
    display_en: dict[str, str] = {}
    display_any: dict[str, str] = {}
    try:
        manifest = json.loads(ACTS_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    for document in manifest.get("documents", []):
        act_number = str(document.get("act_number") or "")
        title = str(document.get("act_title") or "")
        bare = _bare_act_title(title)
        if not act_number or not bare:
            continue
        display = title[1:].strip() if title.startswith("*") else title.strip()
        pool.append((act_number, bare, display))
        display_any.setdefault(act_number, display)
        if document.get("language") == "en":
            display_en.setdefault(act_number, display)
    for phrase, act_number in _ACT_ALIASES.items():
        pool.append((act_number, _normalize_act_text(phrase), None))
    return pool, {**display_any, **display_en}


def _contains_token_run(haystack: str, needle: str) -> bool:
    """Whether `needle` appears in `haystack` on word boundaries. Both are
    already normalized to single-space-separated tokens, so padding each with
    a space and checking substring containment is a whole-token match without
    the cost of a per-title regex."""
    return f" {haystack} ".find(f" {needle} ") != -1


def _resolve_act_title(query: str) -> tuple[str | None, str | None] | None:
    """Resolve via a title/alias match, or None if none was found at all.

    None (not a tuple) means "try the bare 'Act <number>' fallback next";
    an actual `(None, None)` means titles matched ambiguously and the caller
    must stop there rather than let a stray "Act <number>" - e.g. the "1950"
    in "Evidence Act 1950" - override that ambiguity with a wrong guess.
    """
    pool, fallback_display = _act_title_index()
    normalized_query = _normalize_act_text(query)
    matched = [
        (act_number, title, display)
        for act_number, title, display in pool
        if _contains_token_run(normalized_query, title)
    ]
    if not matched:
        return None

    # A shorter match nested inside another, longer match for a *different*
    # Act is redundant - e.g. "Employment Act" nests inside "Children and
    # Young Persons (Employment) Act" - so it shouldn't make an otherwise
    # precise query read as ambiguous. Keep only the maximal matches.
    maximal = [
        (act_number, title, display)
        for act_number, title, display in matched
        if not any(
            other_act != act_number and len(other_title) > len(title)
            and _contains_token_run(other_title, title)
            for other_act, other_title, _ in matched
        )
    ]
    acts = {act_number for act_number, _, _ in maximal}
    if len(acts) != 1:
        # More than one Act's title is present in the query - a wrong Act is
        # worse than no Act, so this must not guess (issue #62).
        return None, None

    act_number = next(iter(acts))
    displays = [display for a, _, display in maximal if a == act_number and display]
    display = max(displays, key=len) if displays else fallback_display.get(act_number)
    return act_number, display


def extract_act_hint(query: str) -> tuple[str | None, str | None]:
    """Resolve an Act reference in free text to (act_number, act_title).

    Matches the query against every Act's title(s) in ACTS_MANIFEST_PATH -
    normalized, so casing and punctuation don't matter - falling back to
    `_ACT_ALIASES` for the handful of names the manifest can't supply, then to
    a bare 'Act <number>'. Returns (None, None) when nothing matches, or when
    the query's text matches more than one Act.
    """
    resolved = _resolve_act_title(query)
    if resolved is not None:
        return resolved

    bare_number = _ACT_NUMBER_RE.search(query)
    if bare_number:
        return bare_number.group(1).upper(), None
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


def _has_division_column(cur) -> bool:
    """Return whether `chunks.division` exists on this database.

    Same reason as `_has_provenance_schema`: the column arrives with the corpus
    migration, and retrieval has to keep answering on a database that has not run
    it yet rather than waiting for a flag day.
    """
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'chunks'
            AND column_name = 'division'
        ) AS available
        """
    )
    row = cur.fetchone()
    return bool(row and row["available"])


def has_path_column(cur) -> bool:
    """Return whether `chunks.path` exists on this database.

    Same reason as `_has_division_column`. Public (no leading underscore) since
    `evals/assertions.py` and `api/evals.py` need the same schema-existence
    check before running a query that references `path` directly, rather than
    duplicating this check a third time - and, unlike this module's other
    schema checks, those callers' cursors are plain tuple cursors rather than
    `RealDictCursor`, so this tolerates either row shape.
    """
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'chunks'
            AND column_name = 'path'
        ) AS available
        """
    )
    row = cur.fetchone()
    if row is None:
        return False
    try:
        return bool(row["available"])
    except (TypeError, KeyError, IndexError):
        return bool(row[0])


def _select_columns(provenance: bool, division: bool = False, path: bool = False) -> str:
    # Rows ingested before the column existed are body sections, because the
    # extractor that wrote them kept only one chunk per section number.
    division_column = (
        f"COALESCE({'c.' if provenance else ''}division, 'body') AS division"
        if division
        else "'body'::text AS division"
    )
    prefix = "c." if provenance else ""
    path_column = (
        f"COALESCE({prefix}path, 's.' || {prefix}section_number) AS path"
        if path
        else "NULL::text AS path"
    )
    if not provenance:
        return (
            "act_number, act_title, section_number, content, page_number, language, "
            "NULL::text AS document_id, NULL::text AS extraction_id, "
            "NULL::text AS content_sha256, page_number AS page_start, "
            f"page_number AS page_end, NULL::text AS source_url, {division_column}, {path_column}"
        )
    return (
        "c.act_number, c.act_title, c.section_number, c.content, c.page_number, c.language, "
        "c.document_id, c.extraction_id, c.content_sha256, "
        "COALESCE(c.page_start, c.page_number) AS page_start, "
        f"COALESCE(c.page_end, c.page_number) AS page_end, d.source_url, {division_column}, {path_column}"
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
            division = _has_division_column(cur)
            path_available = has_path_column(cur)
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
                SELECT {_select_columns(provenance, division, path_available)},
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
    *,
    document_id: str | None = None,
    extraction_id: str | None = None,
    conn=None,
) -> list[dict]:
    """Exact match on a section number within a specific Act (no embedding call).

    Needs a section plus at least one Act hint (`act_number` or `act_title`);
    returns [] otherwise so callers can fall back to semantic search. English
    chunks and the exact-act match are ordered first. Pass an open `conn` to
    reuse a connection across several lookups in one request; the caller then
    owns closing it.

    `section` still accepts a bare number, unchanged for the LLM and every
    existing caller (ADR 0018). Internally: an input that parses against the
    path grammar (`s.90A`, `sched.2/para.1`, ...) is matched against the `path`
    column exactly; anything else is matched against `section_number`, which
    only a body row populates now, so an unqualified "section 1" resolves to
    the body one without needing an ordering trick.
    """
    path_query = canonicalize_path(section)
    section_number = extract_section_number(section) or (section or "").strip().upper()
    if not (path_query or section_number) or not (act_number or act_title):
        return []
    if bool(document_id) != bool(extraction_id):
        return []

    title_pattern = f"%{act_title}%" if act_title else ""
    owns_conn = conn is None
    conn = conn or psycopg2.connect(_db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            mode = _retrieval_mode()
            provenance = _has_provenance_schema(cur)
            division = _has_division_column(cur)
            path_available = has_path_column(cur)
            if mode == "verified" and not provenance:
                return []
            if document_id and (not provenance or mode == "legacy"):
                return []
            if path_query and not path_available:
                # No schema to satisfy a path-shaped query against - fall back
                # to semantic search rather than guess at a bare-number match.
                return []
            joins = """
                LEFT JOIN active_corpus_documents a
                  ON a.act_number = c.act_number AND a.language = c.language
                 AND a.document_id = c.document_id AND a.extraction_id = c.extraction_id
                LEFT JOIN corpus_documents d ON d.document_id = c.document_id
            """ if provenance else ""
            provenance_filter = f"AND {_provenance_visibility(mode)}" if provenance else ""
            identity_filter = ""
            identity_params: list[str] = []
            if document_id and extraction_id:
                identity_filter = "AND c.document_id = %s AND c.extraction_id = %s"
                identity_params = [document_id, extraction_id]
            prefix = "c." if provenance else ""
            if path_query and path_available:
                identity_clause = f"{prefix}path = %s"
                identity_value = path_query
            else:
                identity_clause = f"UPPER({prefix}section_number) = %s"
                identity_value = section_number
            cur.execute(
                f"""
                SELECT {_select_columns(provenance, division, path_available)},
                       1.0 AS similarity
                FROM chunks {prefix.rstrip('.')}
                {joins}
                WHERE {identity_clause}
                  AND ({prefix}act_number = %s OR {prefix}act_title ILIKE %s)
                  {provenance_filter}
                  {identity_filter}
                ORDER BY
                  CASE WHEN {prefix}act_number = %s THEN 0 ELSE 1 END,
                  CASE WHEN {prefix}language = 'en' THEN 0 ELSE 1 END
                LIMIT %s
                """,
                (
                    identity_value,
                    act_number or "",
                    title_pattern,
                    *identity_params,
                    act_number or "",
                    EXACT_TOP_K,
                ),
            )
            rows = [dict(row) for row in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()
    return attach_pdf_urls(rows)


def exact_section_lookup_for_document(
    section: str,
    *,
    act_number: str,
    document_id: str,
    extraction_id: str,
    conn=None,
) -> list[dict]:
    """Look up a section only in one active, exact corpus extraction.

    Legacy/unversioned rows and a non-active extraction return no result. This is
    intentionally stricter than ``exact_section_lookup`` so a graph snapshot can
    never be silently mapped to whichever corpus version happens to be latest.
    """
    if not document_id or not extraction_id:
        return []
    kwargs = {"conn": conn} if conn is not None else {}
    return exact_section_lookup(
        section,
        act_number=act_number,
        document_id=document_id,
        extraction_id=extraction_id,
        **kwargs,
    )
