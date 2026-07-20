"""
Step 4 — Extract identity-bound chunks and word-coordinate sidecars.

For each registered immutable reprint in the corpus manifest:
  1. Detect scanned PDFs (avg < 100 chars/page) → flag and skip
  2. Extract text page-by-page with pymupdf
  3. Split into section-level chunks using Malaysian Act numbering conventions
  4. Write a versioned extraction bundle and hash-verified sidecar

Chunk schema adds document_id, extraction_id, content_sha256, and page bounds.

The page_number enables #page=N deep links to the AGC PDF.

Resumable: extraction identity is document bytes + extractor version/config.
"""
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

from scraper.config import (
    INDEX_FILE,
    PDF_EN_DIR,
    CHUNKS_EN_DIR,
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

# Matches section boundaries in Malaysian Acts:
#   "1.  Short title"  "32A.   Admissibility..."  "90A.  Admissibility..."
# Requires digits (1-3), optional uppercase suffix (A, AA, AB), period, 1+ spaces, non-space.
# TOC entries are "N.\n" (nothing after the period on that line) — these do NOT match.
_SECTION_RE = re.compile(r'^(\d{1,3}[A-Z]{0,2})\.\s+\S')

SCANNED_THRESHOLD  = 100   # avg chars/page below this → scanned
MIN_CONTENT_CHARS  = 80    # sections shorter than this are noise (stray TOC matches)


def _load_title_map() -> dict[str, str]:
    """Build {act_number: title_en} from acts_index.json."""
    index = json.loads(Path(INDEX_FILE).read_text(encoding="utf-8"))
    return {a["act_number"]: a.get("title_en", "") for a in index["acts"]}


def _is_scanned(doc: fitz.Document) -> bool:
    total = sum(len(page.get_text()) for page in doc)
    return (total / max(len(doc), 1)) < SCANNED_THRESHOLD


def _extract_chunks(doc: fitz.Document, act_number: str, act_title: str) -> list[dict]:
    """
    Walk pages line-by-line. When a line matches the section pattern, close the
    previous section and start a new one, recording the page number it started on.
    The title line (the non-empty line immediately before the section number) is
    prepended to the content so it's searchable.

    Deduplicates by section number (last occurrence wins): the body version of a
    section always appears after the TOC version, so the last occurrence is canonical.
    """
    raw: list[dict] = []
    current_num   = None
    current_page  = 1
    current_lines: list[str] = []
    prev_line     = ""

    def _flush():
        if not current_num:
            return
        content = "\n".join(l for l in current_lines if l).strip()
        if len(content) >= MIN_CONTENT_CHARS:
            raw.append({
                "act_number":     act_number,
                "act_title":      act_title,
                "section_number": current_num,
                "content":        content,
                "page_number":    current_page,
                "language":       "en",
            })

    for page_num, page in enumerate(doc, 1):
        for line in page.get_text().split("\n"):
            stripped = line.strip()
            m = _SECTION_RE.match(stripped)
            if m:
                _flush()
                current_num   = m.group(1)
                current_page  = page_num
                title_candidate = prev_line.strip()
                if (title_candidate
                        and len(title_candidate) < 120
                        and not title_candidate[0].isdigit()
                        and not title_candidate.startswith("(")):
                    current_lines = [title_candidate, stripped]
                else:
                    current_lines = [stripped]
            elif current_num is not None:
                current_lines.append(stripped)

            prev_line = stripped

    _flush()

    # Deduplicate: section numbers are unique per Act; last occurrence is the body version.
    seen: dict[str, dict] = {}
    for chunk in raw:
        seen[chunk["section_number"]] = chunk
    return list(seen.values())


def extract_act(pdf_path: Path, act_number: str, act_title: str) -> dict:
    """
    Returns a result dict with status ('ok' | 'scanned' | 'error') and chunks list.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.warning("Act %s — failed to open PDF: %s", act_number, exc)
        return {"status": "error", "reason": str(exc), "chunks": []}

    if _is_scanned(doc):
        logger.info("Act %s — scanned PDF, skipping", act_number)
        return {"status": "scanned", "chunks": []}

    chunks = _extract_chunks(doc, act_number, act_title)
    logger.info("Act %s — %d sections extracted", act_number, len(chunks))
    return {"status": "ok", "chunks": chunks}


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
