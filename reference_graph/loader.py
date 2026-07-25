"""Transactional idempotent PostgreSQL loader for promoted graph artifacts only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2

from .artifacts import artifact_hashes, graph_dir, load_artifacts
from .validation import validate_artifacts

MIGRATIONS = tuple(sorted(
    Path(__file__).resolve().parents[1].glob("migrations/*_reference_graph*.sql")
))


def apply_migrations(connection) -> list[str]:
    applied = []
    with connection:
        with connection.cursor() as cursor:
            for path in MIGRATIONS:
                cursor.execute(path.read_text(encoding="utf-8"))
                applied.append(path.name)
    return applied


def load_promoted(connection, root: Path, document_id: str) -> dict[str, int]:
    directory = graph_dir(root, document_id)
    validation = validate_artifacts(directory, require_promoted=True)
    if not validation["valid"]:
        raise ValueError("cannot_load_invalid_reference_graph")
    data = load_artifacts(directory)
    document = data["provisions"]["document"]
    hashes = artifact_hashes(directory)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO reference_graph_documents
                       (document_id, corpus_document_id, act_number, source_metadata, artifact_hashes)
                   VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                   ON CONFLICT (document_id) DO UPDATE SET corpus_document_id = EXCLUDED.corpus_document_id,
                   act_number = EXCLUDED.act_number, source_metadata = EXCLUDED.source_metadata,
                   artifact_hashes = EXCLUDED.artifact_hashes, loaded_at = NOW()""",
                (
                    document_id,
                    document["corpus_document_id"],
                    document["act_number"],
                    json.dumps(document),
                    json.dumps(hashes, sort_keys=True),
                ),
            )
            cursor.execute("DELETE FROM reference_graph_edges WHERE document_id = %s", (document_id,))
            cursor.execute("DELETE FROM reference_graph_unresolved WHERE document_id = %s", (document_id,))
            cursor.execute("DELETE FROM reference_graph_provisions WHERE document_id = %s", (document_id,))
            for item in data["provisions"]["provisions"]:
                cursor.execute(
                    """INSERT INTO reference_graph_provisions (document_id, provision_id, version_id, parent_id, kind, label, payload)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)""",
                    (document_id, item["provision_id"], item["version_id"], item["parent_id"], item["kind"], item["label"], json.dumps(item)),
                )
            for item in data["edges"]["edges"]:
                cursor.execute(
                    """INSERT INTO reference_graph_edges (document_id, edge_id, source_provision_id, target_provision_id, payload)
                       VALUES (%s, %s, %s, %s, %s::jsonb)""",
                    (document_id, item["edge_id"], item["source_provision_id"], item["target_provision_id"], json.dumps(item)),
                )
            for item in data["unresolved"]["unresolved"]:
                cursor.execute(
                    """INSERT INTO reference_graph_unresolved (document_id, candidate_id, source_provision_id, reason_code, payload)
                       VALUES (%s, %s, %s, %s, %s::jsonb)""",
                    (document_id, item["candidate_id"], item["source_provision_id"], item["reason_code"], json.dumps(item)),
                )
    return validation["counts"]


def verify_database(
    connection,
    document_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    tables = {"provisions": "reference_graph_provisions", "edges": "reference_graph_edges", "unresolved": "reference_graph_unresolved"}
    with connection.cursor() as cursor:
        counts = {}
        for label, table in tables.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE document_id = %s", (document_id,))
            counts[label] = int(cursor.fetchone()[0])
        if root is None:
            return counts
        cursor.execute(
            "SELECT artifact_hashes FROM reference_graph_documents WHERE document_id = %s",
            (document_id,),
        )
        row = cursor.fetchone()
    expected_validation = validate_artifacts(graph_dir(root, document_id), require_promoted=True)
    expected_counts = {
        key: expected_validation["counts"][key]
        for key in ("provisions", "edges", "unresolved")
    }
    expected_hashes = artifact_hashes(graph_dir(root, document_id))
    loaded_hashes = row[0] if row else None
    return {
        "valid": bool(row) and counts == expected_counts and loaded_hashes == expected_hashes,
        "counts": counts,
        "expected_counts": expected_counts,
        "artifact_hashes": loaded_hashes,
        "expected_artifact_hashes": expected_hashes,
    }


def connect_and_load(database_url: str, root: Path, document_id: str) -> dict[str, int]:
    connection = psycopg2.connect(database_url)
    try:
        return load_promoted(connection, root, document_id)
    finally:
        connection.close()
