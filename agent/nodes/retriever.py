"""
Retriever node — embeds the query and searches pgvector for the top-k chunks.

Searches both English chunks (cross-lingual embedding handles BM and mixed queries).
Attaches the AGC PDF URL (with page anchor) to each chunk for citation deep links.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI

from agent.state import AgentState

load_dotenv()

TOP_K        = 8
METADATA_DIR = Path("data/acts_metadata")

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


def retriever_node(state: AgentState) -> dict:
    query_vec = _embed(state["query"])

    conn = psycopg2.connect(_db_url)
    try:
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
            rows = cur.fetchall()
    finally:
        conn.close()

    pdf_map = _pdf_url_map()
    chunks = []
    for row in rows:
        d = dict(row)
        base_url = pdf_map.get(d["act_number"], "")
        d["pdf_url"] = f"{base_url}#page={d['page_number']}" if base_url and d.get("page_number") else base_url
        chunks.append(d)

    return {"retrieved_chunks": chunks}
