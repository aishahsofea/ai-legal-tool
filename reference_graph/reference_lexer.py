"""Literal-only cross-reference lexer. It never classifies with an external service."""
from __future__ import annotations

from dataclasses import dataclass
import re

_REFERENCE_RE = re.compile(
    r"\b(?P<kind>sections?|subsections?|paragraphs?|subparagraphs?|Parts?|Schedules?)\s+"
    r"(?P<body>(?:\d{1,3}[A-Z]{0,2}(?:\s*\([^)]*\))?|\([^)]*\)|[IVXLCDM]+|First|Second)"
    r"(?:\s*(?:,|and|or|to|–|-)\s*(?:\d{1,3}[A-Z]{0,2}(?:\s*\([^)]*\))?|\([^)]*\)|[IVXLCDM]+|First|Second))*)"
    r"(?:\s+of\s+(?P<act>this Act|the [A-Z][^.\[\n]*? Act \d{4}\s*\[Act\s+\d+\]))?(?![A-Za-z])",
    re.IGNORECASE,
)
_CROSS_ACT_RE = re.compile(
    r"\b(?:the\s+)?(?:[A-Z][A-Za-z’'\-]*\s+){0,14}Act\s+\d{4}\s*\[Act\s+\d+\]",
)
_THIS_ACT_RE = re.compile(r"\bthis Act\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReferenceCandidate:
    literal: str
    start_offset: int
    end_offset: int
    kind: str
    body: str
    act_phrase: str | None


def _is_structural_heading(text: str, start: int, end: int) -> bool:
    """Reject a reference-shaped line that is only a document heading.

    PDF text puts the next Part heading after the final provision on a page, so
    it can fall within the preceding provision's broad page span.  A standalone
    ``PART IV`` labels the document; it is not an explicit relationship.
    """
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip().casefold() == text[start:end].strip().casefold()


def lex(text: str) -> list[ReferenceCandidate]:
    result = [ReferenceCandidate(match.group(0), match.start(), match.end(), match.group("kind").lower(),
                                 match.group("body"), match.group("act")) for match in _REFERENCE_RE.finditer(text)
              if not _is_structural_heading(text, match.start(), match.end())]
    covered = [(item.start_offset, item.end_offset) for item in result]
    for match in _CROSS_ACT_RE.finditer(text):
        if (not _is_structural_heading(text, match.start(), match.end())
                and not any(start <= match.start() and match.end() <= end for start, end in covered)):
            result.append(ReferenceCandidate(match.group(0), match.start(), match.end(), "act", match.group(0), match.group(0)))
    for match in _THIS_ACT_RE.finditer(text):
        if (not _is_structural_heading(text, match.start(), match.end())
                and not any(start <= match.start() and match.end() <= end for start, end in covered)):
            result.append(ReferenceCandidate(match.group(0), match.start(), match.end(), "act", "this Act", "this Act"))
    return sorted(result, key=lambda item: (item.start_offset, item.end_offset, item.literal))
