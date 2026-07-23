"""Transactional idempotent PostgreSQL loader for promoted graph artifacts only."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg2

from .artifacts import graph_dir, load_artifacts
from .validation import validate_artifacts


def load_promoted(connection, root: Path, document_id: str) -> dict[str, int]:
    directory = graph_dir(root, document_id)
    validation = validate_artifacts(directory, require_promoted=True)
    if not validation["valid"]:
        raise ValueError("cannot_load_invalid_reference_graph")
    data = load_artifacts(directory)
    document = data["provisions"]["document"]
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO reference_graph_documents (document_id, corpus_document_id, act_number, source_metadata)
                   VALUES (%s, %s, %s, %s::jsonb)
                   ON CONFLICT (document_id) DO UPDATE SET corpus_document_id = EXCLUDED.corpus_document_id,
                   act_number = EXCLUDED.act_number, source_metadata = EXCLUDED.source_metadata""",
                (document_id, document["corpus_document_id"], document["act_number"], json.dumps(document)),
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


def verify_database(connection, document_id: str) -> dict[str, int]:
    tables = {"provisions": "reference_graph_provisions", "edges": "reference_graph_edges", "unresolved": "reference_graph_unresolved"}
    with connection.cursor() as cursor:
        result = {}
        for label, table in tables.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE document_id = %s", (document_id,))
            result[label] = int(cursor.fetchone()[0])
    return result


def connect_and_load(database_url: str, root: Path, document_id: str) -> dict[str, int]:
    connection = psycopg2.connect(database_url)
    try:
        return load_promoted(connection, root, document_id)
    finally:
        connection.close()
