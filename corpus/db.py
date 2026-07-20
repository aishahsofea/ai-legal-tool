"""Transactional registration, shadow ingestion, activation, and rollback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, Sequence

import psycopg2.extras

from corpus.identity import chunk_set_hash, content_hash
from corpus.models import CorpusDocument, ExtractionRun

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "0001_corpus_provenance.sql"


def apply_migration(connection, path: Path = MIGRATION_PATH) -> None:
    sql = Path(path).read_text(encoding="utf-8")
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)


def register_document(cursor, document: CorpusDocument) -> None:
    cursor.execute(
        """
        INSERT INTO corpus_documents (
            document_id, act_number, act_title, language, asset_key, sha256,
            byte_size, page_count, source_url, detail_url, timeline_date,
            timeline_type, metadata_scraped_at, document_kind, lifecycle_status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  NULLIF(%s, '')::timestamptz, %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET
            lifecycle_status = EXCLUDED.lifecycle_status,
            act_title = EXCLUDED.act_title,
            detail_url = EXCLUDED.detail_url
        WHERE corpus_documents.sha256 = EXCLUDED.sha256
          AND corpus_documents.byte_size = EXCLUDED.byte_size
          AND corpus_documents.page_count = EXCLUDED.page_count
          AND corpus_documents.act_number = EXCLUDED.act_number
          AND corpus_documents.language = EXCLUDED.language
        """,
        (
            document.document_id, document.act_number, document.act_title,
            document.language, document.asset_key, document.sha256,
            document.byte_size, document.page_count, document.source_url,
            document.detail_url, document.timeline_date, document.timeline_type,
            document.metadata_scraped_at, document.document_kind,
            document.lifecycle_status,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("document identity conflicts with immutable database metadata")
    if document.source_url and document.metadata_scraped_at:
        cursor.execute(
            """
            INSERT INTO document_sources (document_id, source_url, observed_at)
            VALUES (%s, %s, %s::timestamptz)
            ON CONFLICT DO NOTHING
            """,
            (document.document_id, document.source_url, document.metadata_scraped_at),
        )


def register_source_observation(cursor, observation: dict[str, str]) -> None:
    cursor.execute(
        """
        INSERT INTO document_sources (document_id, source_url, observed_at)
        VALUES (%s, %s, %s::timestamptz)
        ON CONFLICT DO NOTHING
        """,
        (
            observation["document_id"], observation["source_url"],
            observation["observed_at"],
        ),
    )


def register_extraction(cursor, run: ExtractionRun, *, status: str | None = None) -> None:
    sidecar = run.coordinate_sidecar
    cursor.execute(
        """
        INSERT INTO extraction_runs (
            extraction_id, document_id, extractor, extractor_version,
            configuration_hash, chunk_set_hash, chunk_count,
            sidecar_asset_key, sidecar_sha256, sidecar_byte_size,
            sidecar_format, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (extraction_id) DO UPDATE SET
            status = EXCLUDED.status
        WHERE extraction_runs.document_id = EXCLUDED.document_id
          AND extraction_runs.extractor = EXCLUDED.extractor
          AND extraction_runs.extractor_version = EXCLUDED.extractor_version
          AND extraction_runs.configuration_hash = EXCLUDED.configuration_hash
          AND extraction_runs.chunk_set_hash = EXCLUDED.chunk_set_hash
          AND extraction_runs.chunk_count = EXCLUDED.chunk_count
          AND extraction_runs.sidecar_asset_key IS NOT DISTINCT FROM EXCLUDED.sidecar_asset_key
          AND extraction_runs.sidecar_sha256 IS NOT DISTINCT FROM EXCLUDED.sidecar_sha256
          AND extraction_runs.sidecar_byte_size IS NOT DISTINCT FROM EXCLUDED.sidecar_byte_size
          AND extraction_runs.sidecar_format IS NOT DISTINCT FROM EXCLUDED.sidecar_format
        """,
        (
            run.extraction_id, run.document_id, run.extractor,
            run.extractor_version, run.configuration_hash, run.chunk_set_hash,
            run.chunk_count, sidecar.asset_key if sidecar else None,
            sidecar.sha256 if sidecar else None,
            sidecar.byte_size if sidecar else None,
            sidecar.format if sidecar else None, status or run.status,
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("extraction identity conflicts with immutable database metadata")


def validate_bundle(bundle: dict, document: CorpusDocument, run: ExtractionRun) -> list[dict]:
    if bundle.get("schema_version") != 2:
        raise ValueError("unsupported extraction bundle")
    identity = bundle.get("document", {})
    if (
        identity.get("document_id") != document.document_id
        or identity.get("sha256") != document.sha256
        or int(identity.get("byte_size", -1)) != document.byte_size
        or int(identity.get("page_count", -1)) != document.page_count
    ):
        raise ValueError("extraction bundle document identity mismatch")
    if bundle.get("extraction", {}).get("extraction_id") != run.extraction_id:
        raise ValueError("extraction bundle run identity mismatch")
    chunks = bundle.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != run.chunk_count:
        raise ValueError("extraction bundle chunk count mismatch")
    for chunk in chunks:
        if (
            chunk.get("document_id") != document.document_id
            or chunk.get("extraction_id") != run.extraction_id
            or chunk.get("language") != document.language
            or chunk.get("act_number") != document.act_number
            or chunk.get("content_sha256") != content_hash(chunk.get("content"))
        ):
            raise ValueError("chunk provenance or content hash mismatch")
    if chunk_set_hash(chunks) != run.chunk_set_hash:
        raise ValueError("extraction bundle chunk-set hash mismatch")
    return chunks


def ingest_extraction(
    connection,
    document: CorpusDocument,
    run: ExtractionRun,
    bundle: dict,
    embeddings: Sequence[Sequence[float]],
) -> None:
    """Replace one exact extraction atomically after all embeddings exist."""
    chunks = validate_bundle(bundle, document, run)
    if len(embeddings) != len(chunks):
        raise ValueError("embedding count does not match extraction")
    records = [
        (
            chunk["act_number"], chunk.get("act_title", ""),
            chunk["section_number"], chunk["content"], chunk["page_start"],
            chunk["language"], embedding, document.document_id,
            run.extraction_id, chunk["content_sha256"], chunk["page_start"],
            chunk["page_end"], ordinal,
        )
        for ordinal, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    with connection:
        with connection.cursor() as cursor:
            register_document(cursor, document)
            register_extraction(cursor, run, status="pending")
            cursor.execute("DELETE FROM chunks WHERE extraction_id = %s", (run.extraction_id,))
            psycopg2.extras.execute_values(
                cursor,
                """
                INSERT INTO chunks (
                    act_number, act_title, section_number, content, page_number,
                    language, embedding, document_id, extraction_id,
                    content_sha256, page_start, page_end, chunk_ordinal
                ) VALUES %s
                """,
                records,
                template="(%s,%s,%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s)",
            )
            cursor.execute(
                "SELECT COUNT(*) FROM chunks WHERE extraction_id = %s",
                (run.extraction_id,),
            )
            if cursor.fetchone()[0] != run.chunk_count:
                raise ValueError("database extraction count verification failed")
            cursor.execute(
                "UPDATE extraction_runs SET status = 'ready' WHERE extraction_id = %s",
                (run.extraction_id,),
            )


def activate(connection, document: CorpusDocument, run: ExtractionRun) -> None:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT document_id, extraction_id
                FROM active_corpus_documents
                WHERE act_number = %s AND language = %s
                FOR UPDATE
                """,
                (document.act_number, document.language),
            )
            previous = cursor.fetchone()
            cursor.execute(
                """
                SELECT 1 FROM extraction_runs
                WHERE extraction_id = %s AND document_id = %s AND status = 'ready'
                """,
                (run.extraction_id, document.document_id),
            )
            if cursor.fetchone() is None:
                raise ValueError("only a ready exact extraction can be activated")
            cursor.execute(
                """
                INSERT INTO active_corpus_documents
                    (act_number, language, document_id, extraction_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (act_number, language) DO UPDATE SET
                    document_id = EXCLUDED.document_id,
                    extraction_id = EXCLUDED.extraction_id,
                    activated_at = NOW()
                """,
                (document.act_number, document.language, document.document_id, run.extraction_id),
            )
            cursor.execute(
                """
                INSERT INTO corpus_activation_history (
                    act_number, language, document_id, extraction_id,
                    previous_document_id, previous_extraction_id, action
                ) VALUES (%s, %s, %s, %s, %s, %s, 'activate')
                """,
                (
                    document.act_number, document.language, document.document_id,
                    run.extraction_id, previous[0] if previous else None,
                    previous[1] if previous else None,
                ),
            )


def rollback(connection, act_number: str, language: str) -> tuple[str, str]:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT previous_document_id, previous_extraction_id, document_id, extraction_id
                FROM corpus_activation_history
                WHERE act_number = %s AND language = %s
                  AND previous_document_id IS NOT NULL
                ORDER BY activation_id DESC LIMIT 1
                FOR UPDATE
                """,
                (act_number, language),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("no previous active mapping is available")
            previous_document, previous_extraction, current_document, current_extraction = row
            cursor.execute(
                """
                UPDATE active_corpus_documents
                SET document_id = %s, extraction_id = %s, activated_at = NOW()
                WHERE act_number = %s AND language = %s
                """,
                (previous_document, previous_extraction, act_number, language),
            )
            cursor.execute(
                """
                INSERT INTO corpus_activation_history (
                    act_number, language, document_id, extraction_id,
                    previous_document_id, previous_extraction_id, action
                ) VALUES (%s, %s, %s, %s, %s, %s, 'rollback')
                """,
                (
                    act_number, language, previous_document, previous_extraction,
                    current_document, current_extraction,
                ),
            )
    return previous_document, previous_extraction


def load_bundle(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
