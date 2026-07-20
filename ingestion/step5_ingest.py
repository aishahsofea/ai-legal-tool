"""Step 5 — atomically embed and ingest immutable extraction bundles.

All embeddings for one extraction are obtained before database mutation. The
database write then replaces exactly that extraction in one transaction and
verifies the stored row count. Activation remains a separate operator action.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

from corpus.db import apply_migration, ingest_extraction, load_bundle
from corpus.registry import CorpusRegistry

load_dotenv()
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(os.getenv("CORPUS_MANIFEST_PATH", "data/pdfs/manifest.json"))
PDF_ROOT = Path(os.getenv("CORPUS_LOCAL_ROOT", "data/pdfs"))
SIDECAR_ROOT = Path(os.getenv("CORPUS_SIDECAR_ROOT", "data/corpus/sidecars"))
EXTRACTION_ROOT = Path("data/corpus/extractions")
EMBED_MODEL = os.getenv("CORPUS_EMBEDDING_MODEL", "text-embedding-3-small")
BATCH_SIZE = 100


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _embed_all(client: OpenAI, chunks: list[dict]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for offset in range(0, len(chunks), BATCH_SIZE):
        response = client.embeddings.create(
            model=EMBED_MODEL,
            input=[item["content"] for item in chunks[offset:offset + BATCH_SIZE]],
        )
        embeddings.extend(item.embedding for item in response.data)
    if len(embeddings) != len(chunks):
        raise ValueError("embedding provider returned an incomplete batch")
    return embeddings


def _ready_extractions(cursor) -> set[str]:
    cursor.execute(
        """
        SELECT e.extraction_id
        FROM extraction_runs e
        JOIN LATERAL (
            SELECT COUNT(*) AS stored FROM chunks c WHERE c.extraction_id = e.extraction_id
        ) counts ON TRUE
        WHERE e.status = 'ready' AND counts.stored = e.chunk_count
        """
    )
    return {row[0] for row in cursor.fetchall()}


def run_step5() -> None:
    registry = CorpusRegistry(MANIFEST_PATH, asset_root=PDF_ROOT, sidecar_root=SIDECAR_ROOT)
    client = OpenAI()
    connection = _connect()
    try:
        apply_migration(connection)
        with connection.cursor() as cursor:
            completed = _ready_extractions(cursor)
        runs = [
            run for run in registry.extraction_runs.values()
            if run.status == "ready" and run.extraction_id not in completed
        ]
        logger.info("Shadow extractions to ingest: %d", len(runs))
        ingested = failed = 0
        for index, run in enumerate(sorted(runs, key=lambda item: item.extraction_id), 1):
            document = registry.get(run.document_id)
            bundle_path = EXTRACTION_ROOT / f"{run.extraction_id}.chunks.json"
            try:
                bundle = load_bundle(bundle_path)
                embeddings = _embed_all(client, bundle.get("chunks", []))
                ingest_extraction(connection, document, run, bundle, embeddings)
            except Exception:
                # No rows for this extraction have been committed: embedding occurs
                # first and ingest_extraction owns one all-or-nothing transaction.
                failed += 1
                logger.exception(
                    "[%d/%d] extraction failed atomically: %s",
                    index, len(runs), run.extraction_id,
                )
                continue
            ingested += 1
            logger.info("[%d/%d] ingested %s (%d chunks)", index, len(runs), run.extraction_id, run.chunk_count)

        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
                    ON chunks USING hnsw (embedding vector_cosine_ops)
                    """
                )
        logger.info("Shadow ingestion complete. ingested=%d failed=%d", ingested, failed)
    finally:
        connection.close()
