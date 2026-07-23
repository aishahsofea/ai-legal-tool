"""PDF text and physical provenance helpers for the offline graph build."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable

import fitz

from .models import Evidence, PageProvenance, Rectangle

_WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class PdfWord:
    text: str
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    line: int
    word: int


@dataclass(frozen=True)
class PdfPage:
    page_number: int
    text: str
    width: float
    height: float
    words: list[PdfWord]


@dataclass(frozen=True)
class PdfText:
    pages: list[PdfPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pdf(path: Path, expected_sha256: str) -> PdfText:
    """Read the checked-in snapshot only after checking its immutable bytes."""
    if sha256_file(path) != expected_sha256:
        raise ValueError("pdf_sha256_mismatch")
    pages: list[PdfPage] = []
    with fitz.open(path) as pdf:
        for index, page in enumerate(pdf):
            words = [
                PdfWord(str(value[4]), index + 1, float(value[0]), float(value[1]), float(value[2]), float(value[3]),
                        int(value[5]), int(value[6]), int(value[7]))
                # Keep MuPDF's native reading order: it is the order of
                # ``page.get_text()`` used for provision offsets.  Coordinate
                # sorting scrambles multi-column schedule text and makes a
                # known literal impossible to map back to its receipt.
                for value in page.get_text("words")
            ]
            pages.append(PdfPage(index + 1, page.get_text(), float(page.rect.width), float(page.rect.height), words))
    return PdfText(pages)


def page_span(pages: Iterable[PdfPage], start: int, end: int) -> str:
    return "\n".join(page.text for page in pages if start <= page.page_number <= end)


def _tokens(text: str) -> list[str]:
    return [token.replace("’", "'").casefold() for token in _WORD_RE.findall(text)]


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    return [
        (match.group(0).replace("’", "'").casefold(), match.start(), match.end())
        for match in _WORD_RE.finditer(text)
    ]


def _rectangles(page: PdfPage, words: list[PdfWord]) -> list[Rectangle]:
    by_line: dict[tuple[int, int], list[PdfWord]] = {}
    for word in words:
        by_line.setdefault((word.block, word.line), []).append(word)
    result: list[Rectangle] = []
    for line_words in by_line.values():
        x0, y0 = min(word.x0 for word in line_words), min(word.y0 for word in line_words)
        x1, y1 = max(word.x1 for word in line_words), max(word.y1 for word in line_words)
        result.append(Rectangle(
            x=round(max(0.0, min(1.0, x0 / page.width)), 6),
            y=round(max(0.0, min(1.0, y0 / page.height)), 6),
            width=round(max(0.0, min(1.0, (x1 - x0) / page.width)), 6),
            height=round(max(0.0, min(1.0, (y1 - y0) / page.height)), 6),
        ))
    return result


def _span_provenance(start: int, end: int, pages: list[PdfPage]) -> list[PageProvenance]:
    """Map a known text span to sorted PDF words without re-resolving its literal.

    ``Provision.start_offset`` is measured in exactly the same joined text used by
    the parser.  Mapping that known offset avoids choosing the wrong occurrence of
    a repeated reference on a multi-page provision.
    """
    cursor = 0
    selected: dict[int, tuple[PdfPage, list[PdfWord]]] = {}
    for page in pages:
        text_tokens = _token_spans(page.text)
        word_tokens = [(token, word) for word in page.words for token in _tokens(word.text)]
        if [token for token, _token_start, _token_end in text_tokens] != [token for token, _word in word_tokens]:
            return []
        page_start = cursor
        for (_token, token_start, token_end), (_word_token, word) in zip(text_tokens, word_tokens):
            absolute_start = page_start + token_start
            absolute_end = page_start + token_end
            if absolute_start < end and absolute_end > start:
                selected.setdefault(page.page_number, (page, []))[1].append(word)
        cursor += len(page.text) + 1
    return [
        PageProvenance(page_number, _rectangles(page, words))
        for page_number, (page, words) in sorted(selected.items())
        if words
    ]


def evidence_for_literal(text: str, start: int, end: int, pages: Iterable[PdfPage], *,
                         source_start: int | None = None, index_pages: Iterable[PdfPage] | None = None) -> Evidence:
    """Attach an exact half-open text span and its PDF page/rectangle provenance.

    The builder supplies the parser's source coordinate and its page index, making
    evidence deterministic even where the same literal appears more than once in a
    provision.  The legacy literal search remains for isolated callers without a
    parser-coordinate index.
    """
    literal = text[start:end]
    indexed_pages = list(index_pages) if index_pages is not None else list(pages)
    if source_start is not None:
        return Evidence(literal, start, end, _span_provenance(source_start + start, source_start + end, indexed_pages))
    needle = _tokens(literal)
    matches: list[tuple[PdfPage, list[PdfWord]]] = []
    if needle:
        for page in pages:
            token_words = [(token, word) for word in page.words for token in _tokens(word.text)]
            values = [token for token, _word in token_words]
            width = len(needle)
            for offset in range(0, len(values) - width + 1):
                if values[offset:offset + width] == needle:
                    matches.append((page, [word for _token, word in token_words[offset:offset + width]]))
    provenance = []
    if len(matches) == 1:
        page, matched = matches[0]
        provenance = [PageProvenance(page.page_number, _rectangles(page, matched))]
    return Evidence(literal, start, end, provenance)
