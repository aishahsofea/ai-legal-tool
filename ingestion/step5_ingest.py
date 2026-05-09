"""
Step 5 — Embed section chunks and ingest into pgvector.

Reads data/chunks/en/*.json, calls text-embedding-3-small in batches,
inserts into the chunks table in the local Postgres database.

Resumable: skips acts whose act_number is already present in the DB.
After all data is inserted, rebuilds the HNSW index for fast similarity search.

Cost estimate: ~25,000 chunks × 300 tokens × $0.02/1M = ~$0.15 total.
"""
import json
import logging
import os
import time
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

CHUNKS_DIR   = Path("data/chunks/en")
EMBED_MODEL  = "text-embedding-3-small"
BATCH_SIZE   = 100   # chunks per OpenAI API call
EMBED_DIMS   = 1536


def _connect():
    url = os.environ["DATABASE_URL"]
    return psycopg2.connect(url)


def _already_ingested(cur) -> set[str]:
    cur.execute("SELECT DISTINCT act_number FROM chunks;")
    return {row[0] for row in cur.fetchall()}


def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def _insert_batch(cur, rows: list[dict], embeddings: list[list[float]]) -> None:
    records = [
        (
            r["act_number"],
            r["act_title"],
            r["section_number"],
            r["content"],
            r.get("page_number"),
            r.get("language", "en"),
            emb,
        )
        for r, emb in zip(rows, embeddings)
    ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO chunks
            (act_number, act_title, section_number, content, page_number, language, embedding)
        VALUES %s
        """,
        records,
        template="(%s, %s, %s, %s, %s, %s, %s::vector)",
    )


def run_step5() -> None:
    client = OpenAI()
    conn   = _connect()

    with conn:
        with conn.cursor() as cur:
            done = _already_ingested(cur)
            logger.info("Already ingested: %d acts", len(done))

    chunk_files = sorted(
        CHUNKS_DIR.glob("*.json"),
        key=lambda f: int(f.stem) if f.stem.isdigit() else 0,
    )

    to_process = [f for f in chunk_files if json.loads(f.read_text())[0]["act_number"] not in done
                  if json.loads(f.read_text())]
    # Rebuild skipping empty files
    to_process = []
    for f in chunk_files:
        chunks = json.loads(f.read_text(encoding="utf-8"))
        if not chunks:
            continue
        if chunks[0]["act_number"] in done:
            continue
        to_process.append((f, chunks))

    total_acts   = len(to_process)
    total_chunks = sum(len(c) for _, c in to_process)
    logger.info("Acts to ingest: %d  |  chunks: %d", total_acts, total_chunks)

    ingested_chunks = 0
    ingested_acts   = 0

    with conn:
        with conn.cursor() as cur:
            # Drop ivfflat index — it was created before data existed.
            # We'll create an HNSW index after ingestion instead.
            cur.execute("DROP INDEX IF EXISTS chunks_embedding_idx;")

    for act_idx, (f, chunks) in enumerate(to_process, 1):
        act_number = chunks[0]["act_number"]
        act_title  = chunks[0].get("act_title", "")
        logger.info("[%d/%d] Act %s — %s (%d sections)",
                    act_idx, total_acts, act_number, act_title[:50], len(chunks))

        # Process in batches of BATCH_SIZE
        for batch_start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[batch_start : batch_start + BATCH_SIZE]
            texts = [c["content"] for c in batch]

            try:
                embeddings = _embed_batch(client, texts)
            except Exception as exc:
                logger.error("Embedding failed for act %s batch %d: %s",
                             act_number, batch_start, exc)
                time.sleep(5)
                continue

            with conn:
                with conn.cursor() as cur:
                    _insert_batch(cur, batch, embeddings)

            ingested_chunks += len(batch)

        ingested_acts += 1
        logger.info("  → ingested. Total so far: %d chunks", ingested_chunks)

    logger.info("Ingestion complete. Acts: %d  Chunks: %d", ingested_acts, ingested_chunks)

    # Build HNSW index now that data is loaded — better than ivfflat for
    # incremental inserts and doesn't require pre-training on the full dataset.
    logger.info("Building HNSW index...")
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
                ON chunks USING hnsw (embedding vector_cosine_ops);
            """)
    logger.info("HNSW index built.")

    conn.close()
