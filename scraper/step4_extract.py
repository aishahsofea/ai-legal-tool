"""
Step 4 — Extract identity-bound chunks and word-coordinate sidecars.

Thin CLI entry point. The extraction itself — scanned-PDF detection,
section-level chunking, division boundaries, and hash-verified coordinate
sidecars, all keyed to document identity — lives in
corpus.extraction.extract_manifest; this module just wires the registry to
it and writes the resulting manifest and report to disk.

Resumable: extraction identity is document bytes + extractor version/config.
"""
import logging
from datetime import datetime, timezone
from pathlib import Path

from scraper.config import (
    PDF_EN_DIR,
    EXTRACT_REPORT,
    CORPUS_MANIFEST,
    CORPUS_ASSET_DIR,
    CORPUS_SIDECAR_DIR,
    CORPUS_EXTRACTION_DIR,
)

from corpus.extraction import extract_manifest
from corpus.manifest import dump_json
from corpus.registry import CorpusRegistry

logger = logging.getLogger(__name__)


def run_step4() -> None:
    manifest_path = Path(CORPUS_MANIFEST)
    registry = CorpusRegistry(
        manifest_path,
        asset_root=Path(CORPUS_ASSET_DIR),
        sidecar_root=Path(CORPUS_SIDECAR_DIR),
    )
    selected = [
        document.document_id
        for document in registry.documents.values()
        if document.lifecycle_status in {"registered", "extracted"}
    ]
    logger.info("Step 4: %d immutable documents to process", len(selected))
    manifest, report = extract_manifest(
        registry,
        extraction_root=Path(CORPUS_EXTRACTION_DIR),
        sidecar_root=Path(CORPUS_SIDECAR_DIR),
        document_ids=selected,
        activate_ready=False,
    )
    dump_json(manifest_path, manifest)
    dump_json(Path(EXTRACT_REPORT), report)
    logger.info("Step 4 complete. ready=%d blocked=%d", report["ready"], report["blocked"])
