from unittest.mock import Mock, patch

import pytest

from corpus.db import ingest_extraction, register_extraction, validate_bundle
from corpus.identity import chunk_set_hash, content_hash
from corpus.models import CoordinateSidecar, CorpusDocument, ExtractionRun


def _fixture():
    document = CorpusDocument(
        document_id="act-1-en-sha256-" + "a" * 64,
        act_number="1", act_title="ACT 1", language="en",
        asset_key="statutes/sha256/aa/aa/" + "a" * 64 + ".pdf",
        sha256="a" * 64, byte_size=10, page_count=1,
        source_url="https://example.test/1.pdf", timeline_date="",
        timeline_type="REPRINT", metadata_scraped_at="2026-01-01T00:00:00Z",
    )
    chunks = [{
        "act_number": "1", "act_title": "ACT 1", "section_number": "1",
        "content": "1. Fixture legal content", "content_sha256": content_hash("1. Fixture legal content"),
        "page_number": 1, "page_start": 1, "page_end": 1, "language": "en",
        "document_id": document.document_id, "extraction_id": "extraction-sha256-fixture",
    }]
    run = ExtractionRun(
        extraction_id="extraction-sha256-fixture", document_id=document.document_id,
        extractor="fixture", extractor_version="1", configuration_hash="b" * 64,
        chunk_set_hash=chunk_set_hash(chunks), chunk_count=1, status="ready",
        coordinate_sidecar=CoordinateSidecar(
            asset_key="statutes/extractions/fixture/words.json.gz",
            sha256="c" * 64, byte_size=10,
        ),
    )
    bundle = {
        "schema_version": 2,
        "document": {"document_id": document.document_id, "sha256": document.sha256, "byte_size": 10, "page_count": 1},
        "extraction": run.to_dict(),
        "chunks": chunks,
    }
    return document, run, bundle


class _Cursor:
    rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return (1,)


class _Connection:
    def __init__(self):
        self.entered = False
        self.rolled_back = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, *_args):
        self.rolled_back = exc_type is not None
        return False

    def cursor(self):
        return _Cursor()


def test_bundle_validation_rejects_content_drift_before_database_mutation():
    document, run, bundle = _fixture()
    bundle["chunks"][0]["content"] = "changed"
    connection = _Connection()

    with pytest.raises(ValueError, match="content hash"):
        ingest_extraction(connection, document, run, bundle, [[0.1, 0.2]])

    assert not connection.entered


def test_insert_failure_rolls_back_the_whole_extraction():
    document, run, bundle = _fixture()
    connection = _Connection()
    with patch("corpus.db.psycopg2.extras.execute_values", side_effect=RuntimeError("insert failed")):
        with pytest.raises(RuntimeError, match="insert failed"):
            ingest_extraction(connection, document, run, bundle, [[0.1, 0.2]])

    assert connection.entered and connection.rolled_back


def test_extraction_registration_rejects_immutable_metadata_drift():
    _document, run, _bundle = _fixture()
    cursor = _Cursor()
    cursor.rowcount = 0

    with pytest.raises(ValueError, match="immutable database metadata"):
        register_extraction(cursor, run)
