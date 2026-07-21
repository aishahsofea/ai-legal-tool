"""Document-identity keyed extraction and coordinate-sidecar generation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import fitz

from corpus.identity import (
    chunk_set_hash,
    content_hash,
    extraction_id,
    sha256_file,
    sha256_json,
)
from corpus.models import ActiveDocument, CoordinateSidecar, CorpusDocument, ExtractionRun
from corpus.registry import CorpusRegistry
from corpus.sidecars import SIDECAR_FORMAT, write_sidecar

EXTRACTOR = "malaysian-act-sections-pymupdf"
EXTRACTOR_VERSION = "2.0.0"
SECTION_PATTERN = r"^(\d{1,3}[A-Z]{0,2})\.\s+\S"
SCANNED_THRESHOLD = 100
MIN_CONTENT_CHARS = 80
_SECTION_RE = re.compile(SECTION_PATTERN)
EXTRACTOR_CONFIG = {
    "section_pattern": SECTION_PATTERN,
    "scanned_threshold": SCANNED_THRESHOLD,
    "min_content_chars": MIN_CONTENT_CHARS,
    "deduplication": "last-section-number-wins",
    "page_numbering": "physical-1-based",
}
CONFIGURATION_HASH = sha256_json(EXTRACTOR_CONFIG)


def _is_scanned(pdf: fitz.Document) -> bool:
    return sum(len(page.get_text()) for page in pdf) / max(pdf.page_count, 1) < SCANNED_THRESHOLD


def _extract_chunks(pdf: fitz.Document, document: CorpusDocument) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    current_num: str | None = None
    current_page = 1
    current_lines: list[str] = []
    previous_line = ""

    def flush(page_end: int) -> None:
        if not current_num:
            return
        content = "\n".join(line for line in current_lines if line).strip()
        if len(content) < MIN_CONTENT_CHARS:
            return
        raw.append({
            "act_number": document.act_number,
            "act_title": document.act_title,
            "section_number": current_num,
            "content": content,
            "content_sha256": content_hash(content),
            "page_number": current_page,
            "page_start": current_page,
            "page_end": max(current_page, page_end),
            "language": document.language,
            "document_id": document.document_id,
        })

    for page_number, page in enumerate(pdf, 1):
        for line in page.get_text().split("\n"):
            stripped = line.strip()
            match = _SECTION_RE.match(stripped)
            if match:
                flush(page_number)
                current_num = match.group(1)
                current_page = page_number
                title_candidate = previous_line.strip()
                if (
                    title_candidate
                    and len(title_candidate) < 120
                    and not title_candidate[0].isdigit()
                    and not title_candidate.startswith("(")
                ):
                    current_lines = [title_candidate, stripped]
                else:
                    current_lines = [stripped]
            elif current_num is not None:
                current_lines.append(stripped)
            previous_line = stripped
    flush(pdf.page_count)

    deduplicated: dict[str, dict[str, Any]] = {}
    for chunk in raw:
        deduplicated[chunk["section_number"]] = chunk
    return list(deduplicated.values())


def extract_document(
    registry: CorpusRegistry,
    document: CorpusDocument,
    *,
    extraction_root: Path,
    sidecar_root: Path,
) -> tuple[ExtractionRun, Path]:
    pdf_path = registry.validate(document)
    identity = extraction_id(
        document.document_id, EXTRACTOR, EXTRACTOR_VERSION, CONFIGURATION_HASH
    )
    with fitz.open(pdf_path) as pdf:
        if _is_scanned(pdf):
            raise ValueError("scanned_image_only")
        chunks = _extract_chunks(pdf, document)
    if not chunks:
        raise ValueError("no_chunks")
    for chunk in chunks:
        chunk["extraction_id"] = identity

    sidecar_local = f"{identity}.words.json.gz"
    sidecar_path = Path(sidecar_root) / sidecar_local
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{identity}-", suffix=".words.json.gz", dir=sidecar_path.parent
    )
    os.close(descriptor)
    temporary_sidecar = Path(temporary_name)
    try:
        sidecar_sha, sidecar_size = write_sidecar(
            pdf_path, temporary_sidecar, document.document_id, document.sha256
        )
    except Exception:
        temporary_sidecar.unlink(missing_ok=True)
        raise
    sidecar_key = f"statutes/extractions/{identity}/{sidecar_sha}.words.json.gz"
    sidecar = CoordinateSidecar(
        asset_key=sidecar_key,
        sha256=sidecar_sha,
        byte_size=sidecar_size,
        format=SIDECAR_FORMAT,
        local_path=sidecar_local,
    )
    run = ExtractionRun(
        extraction_id=identity,
        document_id=document.document_id,
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        configuration_hash=CONFIGURATION_HASH,
        chunk_set_hash=chunk_set_hash(chunks),
        chunk_count=len(chunks),
        status="ready",
        coordinate_sidecar=sidecar,
    )
    existing_run = registry.extraction_runs.get(identity)
    if existing_run is not None and existing_run != run:
        temporary_sidecar.unlink(missing_ok=True)
        raise ValueError("extraction_identity_drift")
    if sidecar_path.exists():
        if sidecar_path.stat().st_size != sidecar_size or sha256_file(sidecar_path) != sidecar_sha:
            temporary_sidecar.unlink(missing_ok=True)
            raise ValueError("extraction_identity_drift")
        temporary_sidecar.unlink()
    else:
        os.replace(temporary_sidecar, sidecar_path)
    bundle = {
        "schema_version": 2,
        "document": {
            "document_id": document.document_id,
            "sha256": document.sha256,
            "byte_size": document.byte_size,
            "page_count": document.page_count,
        },
        "extraction": run.to_dict(),
        "chunks": chunks,
    }
    bundle_path = Path(extraction_root) / f"{identity}.chunks.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_bytes = (json.dumps(bundle, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if bundle_path.exists():
        if bundle_path.read_bytes() != bundle_bytes:
            raise ValueError("extraction_identity_drift")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{identity}-", suffix=".chunks.json", dir=bundle_path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(bundle_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, bundle_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    return run, bundle_path


def extract_manifest(
    registry: CorpusRegistry,
    *,
    extraction_root: Path,
    sidecar_root: Path,
    document_ids: Iterable[str] | None = None,
    activate_ready: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    selected = set(document_ids or registry.documents)
    runs = dict(registry.extraction_runs)
    active = dict(registry.active_documents)
    documents = dict(registry.documents)
    results: list[dict[str, Any]] = []
    for identity in sorted(selected):
        document = registry.get(identity)
        if document.document_kind != "reprint" or not document.act_title:
            results.append({"document_id": identity, "status": "blocked", "reason": "metadata_not_eligible"})
            continue
        try:
            run, bundle_path = extract_document(
                registry,
                document,
                extraction_root=extraction_root,
                sidecar_root=sidecar_root,
            )
        except Exception as exc:
            results.append({"document_id": identity, "status": "blocked", "reason": str(exc)})
            continue
        runs[run.extraction_id] = run
        documents[identity] = replace(document, lifecycle_status="extracted")
        if activate_ready:
            key = (document.act_number, document.language)
            previous = active.get(key)
            active[key] = ActiveDocument(
                act_number=document.act_number,
                language=document.language,
                document_id=document.document_id,
                extraction_id=run.extraction_id,
                previous_document_id=previous.document_id if previous else "",
            )
            documents[identity] = replace(documents[identity], lifecycle_status="active")
        results.append({
            "document_id": identity,
            "extraction_id": run.extraction_id,
            "chunk_count": run.chunk_count,
            "chunk_set_hash": run.chunk_set_hash,
            "sidecar_sha256": run.coordinate_sidecar.sha256 if run.coordinate_sidecar else "",
            "bundle": bundle_path.name,
            "status": "ready",
        })

    manifest = {
        "schema_version": 2,
        "identity_algorithm": "sha256",
        "documents": [documents[key].to_dict() for key in sorted(documents)],
        "extraction_runs": [runs[key].to_dict() for key in sorted(runs)],
        "active_documents": [
            active[key].to_dict() for key in sorted(active)
        ],
        "aliases": dict(sorted(registry.aliases.items())),
        "source_observations": list(registry.source_observations),
    }
    report = {
        "schema_version": 1,
        "ready": sum(item["status"] == "ready" for item in results),
        "blocked": sum(item["status"] == "blocked" for item in results),
        "documents": results,
    }
    return manifest, report
