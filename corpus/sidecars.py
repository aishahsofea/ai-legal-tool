"""Deterministic PyMuPDF word-coordinate sidecars bound to exact PDF bytes."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import fitz

from corpus.identity import canonical_json_bytes, file_digests

SIDECAR_FORMAT = "pymupdf-words-v1+gzip"


def sidecar_payload(pdf: fitz.Document, document_id: str, document_sha256: str) -> dict:
    """Words come from whatever document the caller opened -- the original for a
    text-layer PDF, or the OCR'd copy for a scanned one (ADR 0019), so this never
    opens pdf_path itself: the caller decides which bytes produced the text."""
    pages = []
    for page_index, page in enumerate(pdf):
        words = []
        for item in page.get_text("words", sort=True):
            x0, y0, x1, y1, raw, block, line, word = item[:8]
            words.append([
                round(float(x0), 4),
                round(float(y0), 4),
                round(float(x1), 4),
                round(float(y1), 4),
                str(raw),
                int(block),
                int(line),
                int(word),
            ])
        pages.append({
            "page_number": page_index + 1,
            "width": round(float(page.rect.width), 4),
            "height": round(float(page.rect.height), 4),
            "rotation": int(page.rotation),
            "words": words,
        })
    return {
        "schema_version": 1,
        "document_id": document_id,
        "document_sha256": document_sha256,
        "pymupdf_version": fitz.VersionBind,
        "pages": pages,
    }


def write_sidecar(
    pdf: fitz.Document,
    output_path: Path,
    document_id: str,
    document_sha256: str,
) -> tuple[str, str, int]:
    payload = sidecar_payload(pdf, document_id, document_sha256)
    encoded = gzip.compress(canonical_json_bytes(payload), compresslevel=9, mtime=0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    sha256, md5 = file_digests(output_path)
    return sha256, md5, len(encoded)


def read_sidecar_bytes(encoded: bytes, document_id: str, document_sha256: str) -> dict:
    try:
        payload = json.loads(gzip.decompress(encoded).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("coordinate sidecar could not be decoded") from exc
    if (
        payload.get("schema_version") != 1
        or payload.get("document_id") != document_id
        or payload.get("document_sha256") != document_sha256
        or not isinstance(payload.get("pages"), list)
    ):
        raise ValueError("coordinate sidecar identity mismatch")
    return payload


def read_sidecar(path: Path, document_id: str, document_sha256: str) -> dict:
    try:
        encoded = path.read_bytes()
    except OSError as exc:
        raise ValueError("coordinate sidecar could not be read") from exc
    return read_sidecar_bytes(encoded, document_id, document_sha256)
