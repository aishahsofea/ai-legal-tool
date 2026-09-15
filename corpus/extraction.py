"""Document-identity keyed extraction and coordinate-sidecar generation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
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
EXTRACTOR_VERSION = "2.2.0"
SECTION_PATTERN = r"^(\d{1,3}[A-Z]{0,2})\.\s+\S"
# Headings that end one run of numbering and start another: the schedules at the
# back of an Act restart at 1, and so do the entries in its list of amendments.
# Anchored at both ends so a body line that merely mentions a schedule is not a
# boundary; "SCHEDULE OF FEES" is missed for the same reason, which leaves that
# Act exactly where it is today rather than splitting it in the wrong place.
DIVISION_PATTERN = (
    r"^(?:(?:[A-Z][A-Z\- ]{0,40}\s{1,4})?SCHEDULE(?:\s{1,4}[A-Z0-9]{1,3})?"
    r"|JADUAL(?:\s{1,4}[A-Z0-9][A-Z0-9\- ]{0,24})?"
    r"|LISTS?\s{1,4}OF\s{1,4}AMENDMENTS"
    r"|SENARAI\s{1,4}PINDAAN)$"
)
# A heading is centred and a sentence is not, which is what separates
# "FIRST SCHEDULE" from "as specified in the First Schedule." Measured on Act 777:
# the headings sit within 0.005 of the page width of centre, the running prose at
# 0.13 and beyond. Centring does not separate a real heading from the copy in the
# table of contents — Act 512 centres both — `_division_boundaries` does that.
DIVISION_CENTRE_TOLERANCE = 0.05
DIVISION_HEADING_MAX_CHARS = 60
# Act 588 prints its heading as "Schedule" where Act 777 prints "FIRST SCHEDULE",
# so the pattern is matched against the uppercased line. Requiring every word to
# start uppercase is what keeps prose out: "in the Schedule" is not a heading.
DIVISION_HEADING_CASE = "every-word-starts-uppercase"
# AGC marks a heading that carries a footnote with a leading asterisk, the same
# way it marks Act titles ("*COMPANIES ACT 2016"). Act 177 prints
# "*FIRST SCHEDULE". The asterisk is not part of the heading.
DIVISION_HEADING_MARKERS = "*"
BODY_DIVISION = "body"
SCANNED_THRESHOLD = 100
MIN_CONTENT_CHARS = 80
_SECTION_RE = re.compile(SECTION_PATTERN)
_DIVISION_RE = re.compile(DIVISION_PATTERN)
EXTRACTOR_CONFIG = {
    "section_pattern": SECTION_PATTERN,
    "division_pattern": DIVISION_PATTERN,
    "division_centre_tolerance": DIVISION_CENTRE_TOLERANCE,
    "division_heading_max_chars": DIVISION_HEADING_MAX_CHARS,
    "division_heading_case": DIVISION_HEADING_CASE,
    "division_heading_markers": DIVISION_HEADING_MARKERS,
    "scanned_threshold": SCANNED_THRESHOLD,
    "min_content_chars": MIN_CONTENT_CHARS,
    "division_boundary": "last-run-per-heading-dropping-a-leading-division-longer-than-the-body",
    "deduplication": "last-section-number-wins-within-division",
    "page_numbering": "physical-1-based",
    "division_content": "kept-as-its-own-chunk-even-without-a-numbered-paragraph",
}
CONFIGURATION_HASH = sha256_json(EXTRACTOR_CONFIG)


def _is_scanned(pdf: fitz.Document) -> bool:
    return sum(len(page.get_text()) for page in pdf) / max(pdf.page_count, 1) < SCANNED_THRESHOLD


def _is_heading_case(text: str) -> bool:
    words = text.split()
    return bool(words) and all(word[0].isupper() or word[0].isdigit() for word in words)


def _division_headings(page: fitz.Page) -> set[str]:
    """Division headings printed on this page, as the plain text layer spells them.

    Matching on the text rather than the position lets the caller keep walking
    `page.get_text()` lines, so two schedules that start on the same page land in
    the order they are printed and the chunk text itself does not change.
    """
    width = page.rect.width or 1.0
    headings: set[str] = set()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            heading = "".join(span["text"] for span in line["spans"]).strip()
            candidate = heading.lstrip(DIVISION_HEADING_MARKERS).strip()
            if (
                len(candidate) > DIVISION_HEADING_MAX_CHARS
                or not _is_heading_case(candidate)
                or not _DIVISION_RE.match(candidate.upper())
            ):
                continue
            left, _, right, _ = line["bbox"]
            if abs((left + right) / 2 - width / 2) / width <= DIVISION_CENTRE_TOLERANCE:
                headings.add(heading)
    return headings


def _last_run_start(pages: list[int]) -> int:
    """First page of the final consecutive run in an ascending page list."""
    start = pages[-1]
    for page in reversed(pages[:-1]):
        if start - page > 1:
            break
        start = page
    return start


def _division_boundaries(pdf: fitz.Document) -> dict[int, set[str]]:
    """Where each division starts, keyed by page.

    A heading is printed twice: once in the table of contents at the front, once
    over the division itself at the back, and both are centred — Act 512 sets the
    two copies at the same offset. The later copy is the real one, the same
    reasoning that makes last-wins right for section numbers. A heading repeated
    across consecutive pages is a running head, so the run counts once, from its
    first page.
    """
    occurrences: dict[str, list[int]] = {}
    for page_number, page in enumerate(pdf, 1):
        for heading in _division_headings(page):
            occurrences.setdefault(heading, []).append(page_number)
    boundaries: dict[int, set[str]] = {}
    for heading, pages in occurrences.items():
        boundaries.setdefault(_last_run_start(pages), set()).add(heading)

    # Act 593 prints "FIRST SCHEDULE" in its table of contents and never again,
    # so last-wins leaves a boundary on page 24 of 369 that would file the whole
    # body under a schedule. Schedules are back matter: a division that runs
    # longer than the body it leaves behind is a table-of-contents copy. Dropping
    # it returns that Act to the single undivided run of numbering it has today,
    # which is the safe direction to be wrong in.
    while boundaries:
        ordered = sorted(boundaries)
        first = ordered[0]
        end = ordered[1] if len(ordered) > 1 else pdf.page_count + 1
        if end - first <= first - 1:
            break
        del boundaries[first]
    return boundaries


def _extract_chunks(pdf: fitz.Document, document: CorpusDocument) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    current_num: str | None = None
    current_page = 1
    current_lines: list[str] = []
    current_division = BODY_DIVISION
    previous_line = ""

    def flush(page_end: int) -> None:
        if current_num is None:
            return
        content = "\n".join(line for line in current_lines if line).strip()
        if len(content) < MIN_CONTENT_CHARS:
            return
        raw.append({
            "act_number": document.act_number,
            "act_title": document.act_title,
            "section_number": current_num,
            "division": current_division,
            "content": content,
            "content_sha256": content_hash(content),
            "page_number": current_page,
            "page_start": current_page,
            "page_end": max(current_page, page_end),
            "language": document.language,
            "document_id": document.document_id,
        })

    boundaries = _division_boundaries(pdf)
    for page_number, page in enumerate(pdf, 1):
        headings = boundaries.get(page_number, frozenset())
        for line in page.get_text().split("\n"):
            stripped = line.strip()
            if stripped in headings:
                flush(page_number)
                current_division = stripped
                # A schedule's own text rarely restarts at "1." on the first line
                # under its heading (Act 512's Second Schedule is a reprinted
                # Geneva Convention numbered "ARTICLE 1"), so this can't wait for
                # a numbered paragraph the way a fresh document waits for its
                # first section. "" is not a real section number `_SECTION_RE`
                # can ever produce, so it can't collide with one; flush() below
                # drops it via MIN_CONTENT_CHARS if nothing follows before the
                # next boundary.
                current_num = ""
                current_page = page_number
                current_lines = []
                previous_line = stripped
                continue
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

    # Last occurrence still wins, because the table of contents copy of a section
    # is printed before the body copy. Keying on the division as well stops a
    # schedule paragraph 1, printed after the body, from taking section 1 with it.
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in raw:
        deduplicated[(chunk["division"], chunk["section_number"])] = chunk
    return list(deduplicated.values())


# A line repeated in the same page-relative band on a good fraction of a
# document's pages is running furniture (page headers, footers, running
# titles), not content — a header survives at the same offset for a whole
# document, where an isolated centred heading like Act 512's "ARTICLE 20"
# never repeats. The 25% floor is high enough that one schedule's heading,
# which only recurs across its own run of pages, cannot trip it.
FURNITURE_BAND_FRACTION = 0.08
FURNITURE_MIN_PAGES = 3
FURNITURE_MIN_PAGE_FRACTION = 0.25


@dataclass(frozen=True)
class ExtractionAccounting:
    """Where a document's characters went, independent of what `_extract_chunks` kept.

    Every line `_line_records` sees lands in exactly one bucket: `assigned`
    (inside a chunk that survived dedup), `classified` (a recognised
    header/footer, or a section candidate the length floor or dedup
    dropped), or `unassigned` — the mystery this issue exists to surface.
    """

    pdf_chars: int
    assigned_chars: int
    classified_chars: int
    unassigned_chars: int

    def to_dict(self) -> dict[str, int]:
        return {
            "pdf_chars": self.pdf_chars,
            "assigned_chars": self.assigned_chars,
            "classified_chars": self.classified_chars,
            "unassigned_chars": self.unassigned_chars,
        }


def _line_records(pdf: fitz.Document) -> list[tuple[int, float, str]]:
    """Every non-blank text line as (page_number, vertical position 0..1, stripped text).

    Reads `page.get_text("dict")`, the block form with bounding boxes that
    `_extract_chunks` does not use, in a second read-only pass over the same
    PDF — so nothing here can change what `_extract_chunks` returns.
    """
    records: list[tuple[int, float, str]] = []
    for page_number, page in enumerate(pdf, 1):
        height = page.rect.height or 1.0
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                stripped = "".join(span["text"] for span in line["spans"]).strip()
                if not stripped:
                    continue
                top, bottom = line["bbox"][1], line["bbox"][3]
                records.append((page_number, (top + bottom) / 2 / height, stripped))
    return records


def _furniture_lines(records: list[tuple[int, float, str]], page_count: int) -> set[str]:
    """Text repeating near the top or bottom of enough pages to be running furniture."""
    band_pages: dict[str, set[int]] = {}
    for page_number, position, text in records:
        if FURNITURE_BAND_FRACTION < position < 1 - FURNITURE_BAND_FRACTION:
            continue
        band_pages.setdefault(text, set()).add(page_number)
    threshold = max(FURNITURE_MIN_PAGES, int(page_count * FURNITURE_MIN_PAGE_FRACTION))
    return {text for text, pages in band_pages.items() if len(pages) >= threshold}


def _candidate_eligible(chars: int, lines: int) -> bool:
    """Mirrors `_extract_chunks.flush`'s `"\\n".join(...)` length floor without building the string."""
    return chars + max(0, lines - 1) >= MIN_CONTENT_CHARS


def _extraction_accounting(pdf: fitz.Document, document: CorpusDocument) -> ExtractionAccounting:
    """Label every text line chunk/furniture/unassigned, mirroring `_extract_chunks`'s control flow.

    Follows the same section pattern, division boundaries, MIN_CONTENT_CHARS
    floor, and last-wins dedup by (division, section_number), so a
    candidate's fate here matches its fate there — but it never calls
    `_extract_chunks` or touches its output. This is independent
    measurement: a bug here cannot change a chunk. A candidate that loses
    the length floor or the dedup is table-of-contents-shaped noise by the
    same reasoning `MIN_CONTENT_CHARS` and last-wins already encode, so both
    land in `classified`, alongside recognised header/footer furniture. A
    division's own content is a candidate under key (division, "") from its
    heading onward, exactly like `_extract_chunks`'s `current_num = ""`, so a
    schedule with no numbered paragraphs is `assigned` rather than falling
    through to `unassigned` the way only its heading line still does.
    """
    records = _line_records(pdf)
    furniture = _furniture_lines(records, pdf.page_count)
    boundaries = _division_boundaries(pdf)

    candidates: list[tuple[tuple[str, str], int, bool]] = []
    current_key: tuple[str, str] | None = None
    current_chars = 0
    current_lines = 0
    current_division = BODY_DIVISION
    pdf_chars = 0
    unassigned_chars = 0
    classified_chars = 0

    for page_number, _position, text in records:
        pdf_chars += len(text)
        headings = boundaries.get(page_number, frozenset())
        if text in headings:
            if current_key is not None:
                candidates.append((current_key, current_chars, _candidate_eligible(current_chars, current_lines)))
            current_division = text
            current_key, current_chars, current_lines = (current_division, ""), 0, 0
            unassigned_chars += len(text)
            continue
        match = _SECTION_RE.match(text)
        if match:
            if current_key is not None:
                candidates.append((current_key, current_chars, _candidate_eligible(current_chars, current_lines)))
            current_key = (current_division, match.group(1))
            current_chars = len(text)
            current_lines = 1
            continue
        if current_key is not None:
            current_chars += len(text)
            current_lines += 1
            continue
        if text in furniture:
            classified_chars += len(text)
        else:
            unassigned_chars += len(text)
    if current_key is not None:
        candidates.append((current_key, current_chars, _candidate_eligible(current_chars, current_lines)))

    winners: dict[tuple[str, str], int] = {}
    for key, chars, eligible in candidates:
        if not eligible:
            classified_chars += chars
            continue
        if key in winners:
            classified_chars += winners[key]
        winners[key] = chars
    assigned_chars = sum(winners.values())

    assert pdf_chars == assigned_chars + classified_chars + unassigned_chars, (
        f"extraction accounting lost characters for {document.document_id}"
    )
    return ExtractionAccounting(
        pdf_chars=pdf_chars,
        assigned_chars=assigned_chars,
        classified_chars=classified_chars,
        unassigned_chars=unassigned_chars,
    )


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
        with fitz.open(registry.local_path(document)) as pdf:
            accounting = _extraction_accounting(pdf, document)
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
            **accounting.to_dict(),
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
    ready_results = [item for item in results if item["status"] == "ready"]
    report = {
        "schema_version": 1,
        "ready": sum(item["status"] == "ready" for item in results),
        "blocked": sum(item["status"] == "blocked" for item in results),
        "documents": results,
        "totals": {
            "pdf_chars": sum(item["pdf_chars"] for item in ready_results),
            "assigned_chars": sum(item["assigned_chars"] for item in ready_results),
            "classified_chars": sum(item["classified_chars"] for item in ready_results),
            "unassigned_chars": sum(item["unassigned_chars"] for item in ready_results),
        },
    }
    return manifest, report
