"""Strict token-to-word locator for immutable Receipt Documents."""
from __future__ import annotations

import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal

import fitz

from corpus.sidecars import read_sidecar, read_sidecar_bytes

_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
_APOSTROPHES = "\u2018\u2019\u201b\u2032\uff07"
_TRANSLATION = str.maketrans({**{char: "-" for char in _DASHES}, **{char: "'" for char in _APOSTROPHES}})
_TOKEN_RE = re.compile(r"[^\W_]+(?:['-][^\W_]+)*", re.UNICODE)


def _canonical_text(value: object) -> str:
    return (
        unicodedata.normalize("NFKC", str(value or ""))
        .replace("\u00ad", "")
        .translate(_TRANSLATION)
        .casefold()
    )


def normalized_tokens(value: object) -> list[str]:
    """Legal-word tokens with only representational differences normalized."""
    return _TOKEN_RE.findall(_canonical_text(value))


def contains_normalized_sequence(needle: object, haystack: object) -> bool:
    wanted = normalized_tokens(needle)
    available = normalized_tokens(haystack)
    if not wanted or len(wanted) > len(available):
        return False
    width = len(wanted)
    return any(available[index:index + width] == wanted for index in range(len(available) - width + 1))


@dataclass(frozen=True)
class Rectangle:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class LocatedPage:
    page_number: int
    rectangles: list[Rectangle]


@dataclass(frozen=True)
class LocatorResult:
    status: Literal["matched", "not_found", "ambiguous"]
    fallback_page: int
    pages: list[LocatedPage]


@dataclass(frozen=True)
class _PdfWord:
    raw: str
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    line: int
    word: int


@dataclass(frozen=True)
class _SourceToken:
    value: str
    words: tuple[_PdfWord, ...]


def _line_changed(first: _PdfWord, second: _PdfWord) -> bool:
    return first.page_number != second.page_number or (first.block, first.line) != (second.block, second.line)


def _source_tokens(words: Iterable[_PdfWord]) -> Iterator[_SourceToken]:
    iterator = iter(words)
    current = next(iterator, None)
    while current is not None:
        canonical = _canonical_text(current.raw).strip()
        following = next(iterator, None)
        if (
            canonical.endswith("-")
            and following is not None
            and _line_changed(current, following)
        ):
            combined = f"{canonical[:-1]}{_canonical_text(following.raw)}"
            parts = normalized_tokens(combined)
            if parts:
                yield from (_SourceToken(part, (current, following)) for part in parts)
                current = next(iterator, None)
                continue

        parts = normalized_tokens(current.raw)
        yield from (_SourceToken(part, (current,)) for part in parts)
        current = following


def _extract_words(pdf: fitz.Document, start_page: int) -> Iterator[_PdfWord]:
    for page_index in range(start_page - 1, pdf.page_count):
        page = pdf[page_index]
        for item in page.get_text("words", sort=True):
            x0, y0, x1, y1, raw, block, line, word = item[:8]
            yield _PdfWord(str(raw), page_index + 1, x0, y0, x1, y1, int(block), int(line), int(word))


def _rectangles(
    page_dimensions: dict[int, tuple[float, float]],
    matched: list[_SourceToken],
) -> list[LocatedPage]:
    unique_words: dict[tuple, _PdfWord] = {}
    for token in matched:
        for word in token.words:
            key = (word.page_number, word.block, word.line, word.word, word.x0, word.y0, word.x1, word.y1)
            unique_words[key] = word

    lines: dict[tuple[int, int, int], list[_PdfWord]] = {}
    for word in unique_words.values():
        lines.setdefault((word.page_number, word.block, word.line), []).append(word)

    pages: dict[int, list[Rectangle]] = {}
    for (page_number, _block, _line), line_words in sorted(lines.items()):
        page_width, page_height = page_dimensions[page_number]
        x0 = min(word.x0 for word in line_words)
        y0 = min(word.y0 for word in line_words)
        x1 = max(word.x1 for word in line_words)
        y1 = max(word.y1 for word in line_words)

        def bounded(value: float) -> float:
            return round(min(1.0, max(0.0, value)), 6)

        pages.setdefault(page_number, []).append(Rectangle(
            x=bounded(x0 / page_width),
            y=bounded(y0 / page_height),
            width=bounded((x1 - x0) / page_width),
            height=bounded((y1 - y0) / page_height),
        ))
    return [LocatedPage(page_number, rectangles) for page_number, rectangles in sorted(pages.items())]


def _sidecar_words(payload: dict, start_page: int) -> Iterator[_PdfWord]:
    for page in payload["pages"][start_page - 1:]:
        page_number = int(page["page_number"])
        for item in page["words"]:
            x0, y0, x1, y1, raw, block, line, word = item
            yield _PdfWord(
                str(raw), page_number, float(x0), float(y0), float(x1), float(y1),
                int(block), int(line), int(word),
            )


def _locate(
    words: Iterable[_PdfWord],
    page_dimensions: dict[int, tuple[float, float]],
    evidence_quote: str | None,
    start_page: int,
) -> LocatorResult:
    quote = normalized_tokens(evidence_quote)
    if not quote:
        return LocatorResult("not_found", start_page, [])
    window: deque[_SourceToken] = deque(maxlen=len(quote))
    nearest_page: int | None = None
    nearest_matches: list[list[_SourceToken]] = []
    for token in _source_tokens(words):
        window.append(token)
        if len(window) < len(quote):
            continue
        candidate_page = window[0].words[0].page_number
        if nearest_page is not None and candidate_page > nearest_page:
            break
        if [item.value for item in window] != quote:
            continue
        if nearest_page is None:
            nearest_page = candidate_page
        if candidate_page == nearest_page:
            nearest_matches.append(list(window))
    if not nearest_matches:
        return LocatorResult("not_found", start_page, [])
    if len(nearest_matches) != 1:
        return LocatorResult("ambiguous", start_page, [])
    return LocatorResult("matched", start_page, _rectangles(page_dimensions, nearest_matches[0]))


def locate_evidence(
    path: Path,
    evidence_quote: str | None,
    start_page: int,
    *,
    sidecar_path: Path | None = None,
    sidecar_bytes: bytes | None = None,
    document_id: str = "",
    document_sha256: str = "",
) -> LocatorResult:
    """Locate against verified precomputed coordinates, with a legacy PDF fallback.

    New corpus extraction runs always pass ``sidecar_path``. Reading live PDF words
    remains only for v1 saved receipts and low-level tests during the dual-read window.
    """
    if sidecar_path is not None or sidecar_bytes is not None:
        if sidecar_path is not None and sidecar_bytes is not None:
            raise ValueError("provide only one coordinate sidecar source")
        payload = (
            read_sidecar(sidecar_path, document_id, document_sha256)
            if sidecar_path is not None
            else read_sidecar_bytes(sidecar_bytes or b"", document_id, document_sha256)
        )
        page_count = len(payload["pages"])
        if start_page < 1 or start_page > page_count:
            raise ValueError(f"start_page must be between 1 and {page_count}")
        dimensions = {
            int(page["page_number"]): (float(page["width"]), float(page["height"]))
            for page in payload["pages"]
        }
        return _locate(_sidecar_words(payload, start_page), dimensions, evidence_quote, start_page)

    with fitz.open(path) as pdf:
        if start_page < 1 or start_page > pdf.page_count:
            raise ValueError(f"start_page must be between 1 and {pdf.page_count}")
        dimensions = {
            index + 1: (float(page.rect.width), float(page.rect.height))
            for index, page in enumerate(pdf)
        }
        return _locate(_extract_words(pdf, start_page), dimensions, evidence_quote, start_page)
