"""Parse provision nodes from the one immutable Employment Act snapshot."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Provision, SourceDocument, stable_id, versioned_id
from .pdf_text import PdfPage, PdfText

SECTION_RE = re.compile(r"(?m)^\s*(\d{1,3}[A-Z]{0,2})\.\s*(?=(?:\(\d+[A-Z]?\)|[A-Z]))")
SUBSECTION_RE = re.compile(r"(?m)^\s*\((\d+[A-Z]?)\)\s+")
PARAGRAPH_RE = re.compile(r"(?m)^\s*\(([a-z]{1,3})\)\s+")
SUBPARAGRAPH_RE = re.compile(r"(?m)^\s*\(([ivxlcdm]+)\)\s+", re.IGNORECASE)
PART_RE = re.compile(r"(?m)^\s*PART\s+([XIVLCDM]+[A-Z]?)\s*$", re.IGNORECASE)
SCHEDULE_RE = re.compile(r"(?m)^\s*(FIRST|SECOND)\s+SCHEDULE\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class _Span:
    label: str
    start: int
    end: int
    page_start: int
    page_end: int


def _main_pages(pdf: PdfText) -> list[PdfPage]:
    # The substantive Act begins at printed page 12; PDFs may keep cover/contents first.
    return [page for page in pdf.pages if 12 <= page.page_number <= 111]


def _join(pages: list[PdfPage]) -> tuple[str, list[int]]:
    offsets: list[int] = []
    cursor = 0
    values = []
    for page in pages:
        offsets.append(cursor)
        values.append(page.text)
        cursor += len(page.text) + 1
    return "\n".join(values), offsets


def _pages_for_span(pages: list[PdfPage], offsets: list[int], start: int, end: int) -> tuple[int, int]:
    selected = [page.page_number for page, page_offset in zip(pages, offsets) if page_offset < end and page_offset + len(page.text) >= start]
    if not selected:
        return pages[0].page_number, pages[0].page_number
    return min(selected), max(selected)


def _append(provisions: list[Provision], document: SourceDocument, kind: str, label: str, parent_id: str | None,
            text: str, start: int, end: int, page_start: int, page_end: int, *identity: tuple[str, str]) -> Provision:
    provision_id = stable_id(document.act_number, *identity)
    # A malformed text layer can repeat a legal label (Act 265's section 82 is
    # one example). Preserve the first physical occurrence without fabricating a
    # second statutory identity; later lexical candidates remain reviewable only
    # if they belong to an unambiguous provision node.
    existing = next((item for item in provisions if item.provision_id == provision_id), None)
    if existing is not None:
        return existing
    provision = Provision(provision_id, versioned_id(document.document_id, provision_id), kind, label, parent_id,
                          text[start:end], start, end, page_start, page_end)
    provisions.append(provision)
    return provision


def _children(provisions: list[Provision], document: SourceDocument, section: Provision, text: str,
              section_start: int, section_end: int, page_start: int, page_end: int) -> None:
    subsection_matches = [(match.start(), match.group(1)) for match in SUBSECTION_RE.finditer(text, section_start, section_end)]
    # The first subsection follows the section number on the same printed line,
    # rather than beginning a new line. Include it explicitly.
    heading = re.match(r"\s*\d{1,3}[A-Z]{0,2}\.\s*\((\d+[A-Z]?)\)\s+", text[section_start:section_end])
    if heading is not None:
        subsection_matches.append((section_start + heading.start(1) - 1, heading.group(1)))
    subsection_matches.sort(key=lambda item: item[0])
    for index, (start, number) in enumerate(subsection_matches):
        end = subsection_matches[index + 1][0] if index + 1 < len(subsection_matches) else section_end
        subsection = _append(provisions, document, "subsection", f"{section.label}({number})", section.provision_id,
                             text, start, end, page_start, page_end,
                             ("section", section.label.removeprefix("Section ")), ("subsection", number))
        paragraph_matches = [
            (match.start(), match.group(1)) for match in PARAGRAPH_RE.finditer(text, start, end)
            if match.group(1).lower() not in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
        ]
        for p_index, (p_start, letter) in enumerate(paragraph_matches):
            p_end = paragraph_matches[p_index + 1][0] if p_index + 1 < len(paragraph_matches) else end
            paragraph = _append(provisions, document, "paragraph", f"{subsection.label}({letter})", subsection.provision_id,
                                text, p_start, p_end, page_start, page_end,
                                ("section", section.label.removeprefix("Section ")), ("subsection", number), ("paragraph", letter))
            # A paragraph label such as ``(c)`` is also syntactically a Roman
            # numeral. Its own heading is not a subparagraph.
            sub_matches = [item for item in SUBPARAGRAPH_RE.finditer(text, p_start, p_end) if item.start() > p_start]
            for s_index, sub_match in enumerate(sub_matches):
                s_start = sub_match.start()
                s_end = sub_matches[s_index + 1].start() if s_index + 1 < len(sub_matches) else p_end
                roman = sub_match.group(1).lower()
                _append(provisions, document, "subparagraph", f"{paragraph.label}({roman})", paragraph.provision_id,
                        text, s_start, s_end, page_start, page_end,
                        ("section", section.label.removeprefix("Section ")), ("subsection", number),
                        ("paragraph", letter), ("subparagraph", roman))


def parse_provisions(pdf: PdfText, document: SourceDocument) -> list[Provision]:
    provisions: list[Provision] = [Provision(
        stable_id(document.act_number), versioned_id(document.document_id, stable_id(document.act_number)), "act",
        f"Act {document.act_number}", None, document.act_title, 0, len(document.act_title), 1, pdf.page_count,
    )]
    pages = _main_pages(pdf)
    text, offsets = _join(pages)
    section_matches = list(SECTION_RE.finditer(text))
    for index, match in enumerate(section_matches):
        start = match.start()
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        number = match.group(1)
        page_start, page_end = _pages_for_span(pages, offsets, start, end)
        section = _append(provisions, document, "section", f"Section {number}", stable_id(document.act_number), text,
                          start, end, page_start, page_end, ("section", number))
        _children(provisions, document, section, text, start, end, page_start, page_end)

    # Part headings are deliberate description nodes: they make explicit Part references resolvable
    # without inventing a type outside the Phase 1 node contract.
    for match in PART_RE.finditer(text):
        part = match.group(1).upper()
        page_start, page_end = _pages_for_span(pages, offsets, match.start(), match.end())
        _append(provisions, document, "description", f"Part {part}", stable_id(document.act_number), text,
                match.start(), match.end(), page_start, page_end, ("description", f"part-{part.lower()}"))

    # The supplied receipt ends the Second Schedule on physical page 115. The
    # following amendment table is a different descriptive appendix.
    schedule_pages = [page for page in pdf.pages if 112 <= page.page_number <= 115]
    schedule_text, schedule_offsets = _join(schedule_pages)
    matches = list(SCHEDULE_RE.finditer(schedule_text))
    table_marker = schedule_text.find("TABLE OF AMENDMENTS")
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else (table_marker if table_marker >= 0 else len(schedule_text))
        page_start, page_end = _pages_for_span(schedule_pages, schedule_offsets, start, end)
        name = match.group(1).title()
        _append(provisions, document, "schedule", f"{name} Schedule", stable_id(document.act_number), schedule_text,
                start, end, page_start, page_end, ("schedule", name.lower()))
    return sorted(provisions, key=lambda item: (item.provision_id.count("/"), item.provision_id))
