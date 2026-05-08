"""
Step 4 — Extract section-level chunks from downloaded PDFs.

For each PDF in data/pdfs/en/:
  1. Detect scanned PDFs (avg < 100 chars/page) → flag and skip
  2. Extract text page-by-page with pymupdf
  3. Split into section-level chunks using Malaysian Act numbering conventions
  4. Write data/chunks/en/{act_number}.json

Chunk schema:
  act_number, act_title, section_number, content, page_number, language

The page_number enables #page=N deep links to the AGC PDF.

Resumable: skips acts whose chunk file already exists.
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
)

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
    pdf_dir    = Path(PDF_EN_DIR)
    chunks_dir = Path(CHUNKS_EN_DIR)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    title_map = _load_title_map()

    pdf_files = sorted(pdf_dir.glob("*.pdf"), key=lambda f: int(f.stem) if f.stem.isdigit() else 0)
    logger.info("Step 4: %d PDFs to process", len(pdf_files))

    ok = scanned = failed = skipped = 0
    scanned_acts: list[str] = []

    for i, pdf_path in enumerate(pdf_files, 1):
        act_number = pdf_path.stem
        out_file   = chunks_dir / f"{act_number}.json"

        if out_file.exists():
            skipped += 1
            continue

        act_title = title_map.get(act_number, "")
        logger.info("[%d/%d] Act %s — %s", i, len(pdf_files), act_number, act_title[:60])

        result = extract_act(pdf_path, act_number, act_title)

        if result["status"] == "ok":
            out_file.write_text(
                json.dumps(result["chunks"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            ok += 1
        elif result["status"] == "scanned":
            scanned += 1
            scanned_acts.append(act_number)
        else:
            failed += 1

    logger.info("Step 4 complete. ok=%d scanned=%d failed=%d skipped=%d", ok, scanned, failed, skipped)

    if scanned_acts:
        logger.info("Scanned PDFs (%d) — not ingested: %s", len(scanned_acts), ", ".join(sorted(scanned_acts, key=lambda x: int(x) if x.isdigit() else x)))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok":      ok,
        "scanned": scanned,
        "failed":  failed,
        "skipped": skipped,
        "scanned_acts": scanned_acts,
    }
    report_path = Path(EXTRACT_REPORT)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report written to %s", EXTRACT_REPORT)
