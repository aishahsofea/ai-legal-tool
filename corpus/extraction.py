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
EXTRACTOR_VERSION = "2.6.0"
SECTION_PATTERN = r"^(\d{1,3}[A-Z]{0,2})\.\s+\S"
# A number AGC prints alone on its own line: its title on the line above, its
# text starting on the line after (#72's cohort - 22 documents whose
# SECTION_PATTERN never matches because nothing follows the dot on that
# line). Also a schedule's own paragraph marker printed the same way - Act
# 4's Fifth Schedule numbers its rows "4." / "Barium" / ... - which is why
# this is shared rather than named for the body alone.
BARE_ITEM_PATTERN = r"^(\d{1,3}[A-Z]{0,2})\.$"
# An incorporated instrument's own numbering, reprinted as a schedule rather
# than translated into Malaysian section numbers - Act 512's Geneva
# Conventions number "ARTICLE 1", not "1.". Case-sensitive on purpose: Act
# 512 also cross-references its own articles in running prose ("as defined
# in Article 13"), and AGC's line wrap occasionally splits that reference
# onto its own line ("...in Article" / "13."). Measured over the whole
# document, real headings are uppercase 429 times and a wrapped
# lowercase-initial reference 3 times - the literal case AGC prints is what
# tells them apart.
SCHEDULE_ARTICLE_PATTERN = r"^ARTICLE\s+(\d{1,3}[A-Z]{0,2})\.?$"
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
# The subset of DIVISION_PATTERN that names a division whose own content is
# never an item (#94's scope: "nothing in it is an item"). Narrows, never
# widens, which heading counts as a division boundary - that decision stays
# DIVISION_PATTERN's alone.
AMENDMENTS_DIVISION_PATTERN = r"^(?:LISTS?\s{1,4}OF\s{1,4}AMENDMENTS|SENARAI\s{1,4}PINDAAN)$"
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
# Front matter and the table of contents, from page 1 to the enacting formula
# (ADR 0018). Never addressable and never a chunk - `flush()` only ever fires
# once `current_num` is set, and nothing below ever sets it while this division
# is active - so this exists purely so `_extraction_accounting` can name the
# span instead of leaving it a mystery in `unassigned_chars`.
FRONT_MATTER_DIVISION = "front matter"
# Matched on the opening words only, not the full clause: the clause wraps
# across several lines at a point that shifts between AGC's "REPRINT" and
# "ONLINE VERSION OF UPDATED TEXT" templates (Act 4 splits "as" from
# "follows:" onto separate lines where Act 160 does not), so anchoring on how
# the clause ends is unreliable where its opening line is not. For the same
# reason the royal title after "BE IT ENACTED BY THE" is not matched at all -
# it has three renderings in the corpus (Act 160: "Seri Paduka Baginda Yang
# di-Pertuan Agong"; Act 187: "Yang di-Pertuan Agong"; Ordinance No. 26 of
# 1963: "Duli Yang Maha Mulia Seri Paduka Baginda") - "BE IT ENACTED" alone
# is distinctive enough. "NOW[,] THEREFORE[,]" prefixes a recital in Acts
# that cite constitutional authority (Act 245, Act 440). A meaningful share
# of the corpus has no enacting clause at all: pre-Merdeka Ordinances (Act
# 159, 198, 260, ...) whose AGC reprint carries a commencement date but
# never this clause - `None` from `_enacting_formula_start` is that
# document's real, unmarked state, not a gap in the pattern.
#
# A third phrasing drops "BE" and never names the actor: "NOW,
# THEREFORE, IT IS ENACTED by the Parliament of Malaysia as follows" (Act
# 595), "...IT IS HEREBY ENACTED by the Yang di-Pertuan Agong with the
# advice and consent of Parliament as follows" (Act 373 - a different actor
# again, so the actor still goes unmatched, same reasoning as above), and
# "...pursuant to Article 149 of the Federal Constitution IT IS ENACTED by
# the Parliament of Malaysia as follows" (Act 747, where a whole clause sits
# between "NOW, THEREFORE," and "IT IS ENACTED"). That last shape is why
# this alternative alone carries no leading `^`: Act 747's own physical line
# reads "Constitution IT IS ENACTED by the Parliament of Malaysia as", so
# anchoring at the line start would miss it. Checked against every local
# English document, "IT IS (HEREBY )?ENACTED BY" finds 12 (Act 297, 373,
# 595, 622, 636, 641, 659, 660, 686, 712, 720, 747) and changes none of the
# others' already-detected line - see tests/test_corpus.py's enacting-formula
# fixtures. Act 33/114/198/205 were never part of this gap: their AGC
# reprints carry no enacting clause of any kind (verified by reading each
# one's front matter directly, not inferred from title) - the same
# legitimate `None` as the pre-Merdeka Ordinances above.
#
# Matched per `document.language`, not combined into one pattern the way
# `DIVISION_PATTERN` combines English and Malay, because a schedule can
# carry the *other* language's prose as its own content - Act 144 (en)
# reprints a Malay grant-form schedule whose execution clause starts a line
# with "Diperbuat".
#
# The "bm" pattern requires "diperbuat" to carry its collocate
# ("undang-undang" for the long form, "oleh parlimen malaysia" for the
# short form) rather than matching the bare verb the way the English
# pattern matches "be it enacted" alone, and - unlike the English patterns -
# is tried on each line joined with the one before it as well as alone,
# because a bare "diperbuat" is genuinely ambiguous in Malay legal prose: a
# transitional-provision heading can end a line "...akan \ndiperbuat"
# ("things done in anticipation of this Act being enacted") with nothing
# else on that line, indistinguishable at the single-line level from the
# real clause's own "MAKA, OLEH YANG DEMIKIAN, INILAH DIPERBUAT
# \nUNDANG-UNDANG oleh ..." (Act 587 - AGC splits the clause's distinctive
# collocation across the line break). A bare-word pattern picked the heading
# over the clause on that document, reading its first 68 sections as front
# matter. Requiring the collocate rules out the heading; checking each line
# joined with its predecessor is what still finds a clause AGC has split
# across two lines. The join is a no-op for "en"'s first two alternatives:
# `^` inside `pattern.search(f"{previous} {line}")` can only match at that
# string's start, which happens only when `previous` is empty. The third
# alternative carries no `^`, so the join is live for it too in principle -
# it has simply never been the one to find a match: every local "IT IS
# ENACTED BY" sits on one physical line already.
ENACTING_FORMULA_PATTERNS = {
    "en": (
        r"^(?:NOW\s*,?\s*THEREFORE\s*,?\s*)?BE\s+IT\s+ENACTED\b"
        r"|^ENACTED\s+BY\s+THE\s+PARLIAMENT\s+OF\s+MALAYSIA\b"
        r"|IT\s+IS\s+(?:HEREBY\s+)?ENACTED\s+BY\b"
    ),
    "bm": (
        r"DIPERBUAT(?:KAN)?\s+UNDANG-UNDANG\b"
        r"|DIPERBUAT\s+OLEH\s+PARLIMEN\s+MALAYSIA\b"
    ),
}
# Front matter cannot reasonably be more than half a printed Act, so a match
# past this point is something else reprinted alongside the Act, not its own
# opening - not a guess: measured over every local document with a match
# (859 of 1,124), page 21 already covers 99% of them and the max legitimate
# one is page 35 of 687 (Act 777's real clause, a Companies Act with a table
# of contents to match). Act 136 (Contracts Act 1950, 91 pages) is why this
# exists: its AGC reprint carries, in an APPENDIX on page 87, the full text
# of an amending Act - complete with that Act's own "BE IT ENACTED" - and
# first-occurrence-wins landed on it ahead of nothing at all, since the
# principal Act's own clause does not match this pattern. Every section
# between the real front matter and that appendix read as front matter too.
# The fraction alone shrinks to nothing on a short document - half of a
# 1-page Act is half a page - so the limit is whichever is larger, with a
# floor comfortably above the measured p99.
ENACTING_FORMULA_MAX_PAGE_FRACTION = 0.5
ENACTING_FORMULA_MIN_PAGE_FLOOR = 30
SCANNED_THRESHOLD = 100
MIN_CONTENT_CHARS = 80
_SECTION_RE = re.compile(SECTION_PATTERN)
_BARE_ITEM_RE = re.compile(BARE_ITEM_PATTERN)
_SCHEDULE_ARTICLE_RE = re.compile(SCHEDULE_ARTICLE_PATTERN)
_DIVISION_RE = re.compile(DIVISION_PATTERN)
_AMENDMENTS_DIVISION_RE = re.compile(AMENDMENTS_DIVISION_PATTERN)
_ENACTING_FORMULA_RE = {
    language: re.compile(pattern) for language, pattern in ENACTING_FORMULA_PATTERNS.items()
}
EXTRACTOR_CONFIG = {
    "section_pattern": SECTION_PATTERN,
    "bare_item_pattern": BARE_ITEM_PATTERN,
    "schedule_article_pattern": SCHEDULE_ARTICLE_PATTERN,
    "division_pattern": DIVISION_PATTERN,
    "amendments_division_pattern": AMENDMENTS_DIVISION_PATTERN,
    "division_centre_tolerance": DIVISION_CENTRE_TOLERANCE,
    "division_heading_max_chars": DIVISION_HEADING_MAX_CHARS,
    "division_heading_case": DIVISION_HEADING_CASE,
    "division_heading_markers": DIVISION_HEADING_MARKERS,
    "enacting_formula_patterns": ENACTING_FORMULA_PATTERNS,
    "enacting_formula_max_page_fraction": ENACTING_FORMULA_MAX_PAGE_FRACTION,
    "enacting_formula_min_page_floor": ENACTING_FORMULA_MIN_PAGE_FLOOR,
    "scanned_threshold": SCANNED_THRESHOLD,
    "min_content_chars": MIN_CONTENT_CHARS,
    "division_boundary": "last-run-per-heading-dropping-a-leading-division-longer-than-the-body",
    "front_matter_boundary": "enacting-formula-opening-line-in-document-language-else-undivided",
    "deduplication": "last-path-wins-within-division",
    "page_numbering": "physical-1-based",
    "division_content": "kept-as-its-own-chunk-even-without-a-numbered-paragraph",
    "body_bare_item": "numbered-line-alone-kept-only-when-the-line-above-reads-as-a-title",
    "schedule_item_numbering": "inline-dot-or-bare-numbered-line-or-article-n-never-in-amendments",
    "chunk_identity": "path-qualified-per-adr-0018-section-number-body-only",
}
CONFIGURATION_HASH = sha256_json(EXTRACTOR_CONFIG)


def _is_scanned(pdf: fitz.Document) -> bool:
    return sum(len(page.get_text()) for page in pdf) / max(pdf.page_count, 1) < SCANNED_THRESHOLD


def _is_heading_case(text: str) -> bool:
    words = text.split()
    return bool(words) and all(word[0].isupper() or word[0].isdigit() for word in words)


def _looks_like_title(text: str) -> bool:
    """A short, unnumbered line - what a section's own title looks like
    printed above its heading, whether that heading is inline or, per #72,
    alone on the line below."""
    return bool(text) and len(text) < 120 and not text[0].isdigit() and not text.startswith("(")


_REFERENCE_TAIL_WORDS = {
    "article", "articles", "paragraph", "paragraphs", "section", "sections",
    "clause", "clauses", "part", "parts", "item", "items", "regulation",
    "regulations", "subparagraph", "subparagraphs",
}


def _token_sort_key(token: str) -> tuple[int, str]:
    """A section token ordered by its numeric prefix first, its letter suffix
    second - "16A" sorts after "16" and before "17", matching how AGC
    actually inserts a lettered section between two numbered ones."""
    for index, character in enumerate(token):
        if not character.isdigit():
            return (int(token[:index]), token[index:])
    return (int(token), "")


def _chunk_path(
    division: str,
    is_amendments: bool,
    schedule_ordinal: int | None,
    item_kind: str | None,
    section_number: str,
) -> str | None:
    """A chunk's path-qualified identifier (ADR 0018), or None where the
    division is never addressable (front matter, list of amendments)."""
    if division == BODY_DIVISION:
        return f"s.{section_number}"
    if is_amendments or schedule_ordinal is None:
        return None
    base = f"sched.{schedule_ordinal}"
    return f"{base}/{item_kind}.{section_number}" if section_number else base


def _ends_with_a_reference_word(text: str) -> bool:
    """True when `text` ends in a word like "Article" or "paragraph" - the
    shape a cross-reference takes once AGC's line wrap splits "in Article
    1." into "...in Article" / "1." (Act 148's Montreal Protocol schedule).
    A schedule has no title line to gate a bare item number the way the body
    does (#72), so this is its guard instead: a real paragraph marker never
    has a bare reference noun immediately above it."""
    words = text.split()
    return bool(words) and words[-1].strip(".,;:").lower() in _REFERENCE_TAIL_WORDS


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


def _enacting_formula_start(pdf: fitz.Document, language: str) -> tuple[int, str] | None:
    """Page and text of the line the body's enacting formula opens on.

    Tries each line against the pattern alone and, since a "bm" clause can
    split its distinctive collocation across a line break (see
    `ENACTING_FORMULA_PATTERNS`), joined with the line before it too - a
    no-op for two of "en"'s three alternatives, `^`-anchored so they can only
    match a joined string when there was no line before it (see the comment
    above `ENACTING_FORMULA_PATTERNS` for the third).

    None when `language` has no pattern to try; when this Act's AGC reprint
    carries no enacting clause at all (common in pre-Merdeka Ordinances); and
    when the only match found is past `ENACTING_FORMULA_MAX_PAGE_FRACTION`
    (Act 136 reprints an amending Act's full text, its own enacting formula
    included, in an appendix past the halfway point). Every one of these is
    the signal to leave this document exactly as it stands today: one
    undivided run, no front-matter division, the same fallback
    `_division_boundaries` takes for a boundary it cannot place with
    confidence, rather than guessing and risking the whole document reading
    as front matter.
    """
    pattern = _ENACTING_FORMULA_RE.get(language)
    if pattern is None:
        return None
    page_limit = max(ENACTING_FORMULA_MIN_PAGE_FLOOR, pdf.page_count * ENACTING_FORMULA_MAX_PAGE_FRACTION)
    previous = ""
    for page_number, page in enumerate(pdf, 1):
        if page_number > page_limit:
            return None
        for line in page.get_text().split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if pattern.search(stripped.upper()) or pattern.search(f"{previous} {stripped}".upper()):
                return page_number, stripped
            previous = stripped
    return None


def _extract_chunks(pdf: fitz.Document, document: CorpusDocument) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    current_num: str | None = None
    current_page = 1
    current_lines: list[str] = []
    enacting_start = _enacting_formula_start(pdf, document.language)
    current_division = FRONT_MATTER_DIVISION if enacting_start is not None else BODY_DIVISION
    current_division_is_amendments = False
    current_division_max_token: tuple[int, str] | None = None
    schedule_ordinal_counter = 0
    current_schedule_ordinal: int | None = None
    current_item_kind: str | None = None
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
            "section_number": current_num if current_division == BODY_DIVISION else "",
            "division": current_division,
            "path": _chunk_path(
                current_division, current_division_is_amendments,
                current_schedule_ordinal, current_item_kind, current_num,
            ),
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
            if current_division == FRONT_MATTER_DIVISION:
                # Gated, not just unmatched: a table-of-contents row's number
                # and title can land on one line and match SECTION_PATTERN
                # exactly like a real heading (Act 602's TOC row "19B.
                # Restoration ..." is the real corpus example this guards
                # against - #97). Every line here stays out of `current_lines`
                # so nothing before the boundary can ever start a chunk.
                previous_line = stripped
                if (page_number, stripped) == enacting_start:
                    current_division = BODY_DIVISION
                continue
            if stripped in headings:
                flush(page_number)
                current_division = stripped
                current_division_is_amendments = bool(_AMENDMENTS_DIVISION_RE.match(stripped.upper()))
                if current_division_is_amendments:
                    current_schedule_ordinal = None
                else:
                    schedule_ordinal_counter += 1
                    current_schedule_ordinal = schedule_ordinal_counter
                current_item_kind = None
                current_division_max_token = None
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
            match_is_inline = match is not None
            item_kind = "para" if match_is_inline and current_division != BODY_DIVISION else None
            if match is None and not current_division_is_amendments:
                bare_match = _BARE_ITEM_RE.match(stripped)
                if current_division == BODY_DIVISION:
                    # Only once front matter has a confirmed end (#93): without
                    # that boundary, a real table of contents reads as body
                    # text, number-then-title, and every row of it would
                    # otherwise pass this gate the same way a real split
                    # heading does (Act 595's "ARRANGEMENT OF SECTIONS" has no
                    # detectable enacting formula and measured exactly this).
                    if enacting_start is not None and bare_match and _looks_like_title(previous_line):
                        match = bare_match
                else:
                    match = _SCHEDULE_ARTICLE_RE.match(stripped)
                    if match is not None:
                        item_kind = "art"
                    elif bare_match and not _ends_with_a_reference_word(previous_line):
                        match = bare_match
                        item_kind = "para"
            if match is not None:
                # A run of numbering can restart lower than what is already
                # seen two ways: a schedule with more than one Part (Act 4's
                # Fifth Schedule: Part I ends at 16, Part II starts back at
                # 1), or a division-boundary miss that leaves a reprinted
                # instrument's own subsection numbers ("(1)...(2)...", once
                # per article) reading as if they were fresh body sections
                # (Act 595 (bm): its Second Schedule heading is pruned by
                # `_division_boundaries` for being longer than the body it
                # follows, so every one of the Vienna Convention's 79
                # articles restarts "1" as if it were still body content).
                # Either way, colliding with the lower number's earlier,
                # legitimate occurrence would silently lose it to last-wins
                # dedup - measured at -30,475 characters on Act 4 (en) alone,
                # -51,014 on Act 595 (bm)'s misclassified body.
                #
                # `SECTION_PATTERN`'s inline match is exempt and always wins:
                # it is the established, pre-#94 signal, so it resets the
                # watermark unconditionally rather than being compared
                # against it. That is what lets a document whose real body
                # starts after a run of unrelated high numbers self-correct -
                # Act 318 (bm) has no detectable enacting formula either, so
                # its real table of contents matches inline exactly like a
                # real section ("56. Kuasa mahkamah...") long before the real
                # body begins at "1. Akta ini bolehlah...". Only the two
                # patterns #94 adds - a bare line, or `ARTICLE n` - are
                # compared against the watermark and rejected below it,
                # folding their content into whatever chunk is already open
                # instead of overwriting real content through the dedup that
                # follows. The same reasoning `_division_boundaries` uses to
                # drop an out-of-place heading run: the safe direction to be
                # wrong in.
                token_key = _token_sort_key(match.group(1))
                if match_is_inline:
                    current_division_max_token = token_key
                elif current_division_max_token is not None and token_key < current_division_max_token:
                    match = None
                else:
                    current_division_max_token = token_key
            if match:
                flush(page_number)
                current_num = match.group(1)
                current_item_kind = item_kind
                current_page = page_number
                title_candidate = previous_line.strip()
                if _looks_like_title(title_candidate):
                    current_lines = [title_candidate, stripped]
                else:
                    current_lines = [stripped]
            elif current_num is not None:
                current_lines.append(stripped)
            previous_line = stripped
    flush(pdf.page_count)

    # Last occurrence still wins, because the table of contents copy of a section
    # is printed before the body copy. Keying on path rather than section_number
    # (ADR 0018) stops a schedule paragraph 1, printed after the body, from taking
    # section 1 with it - and, unlike the division heading text alone, also tells
    # apart two schedules that print the identical bare "Schedule" heading with no
    # ordinal word (Act 588-style), since path disambiguates by appearance order.
    deduplicated: dict[tuple[str, str | None], dict[str, Any]] = {}
    for chunk in raw:
        deduplicated[(chunk["division"], chunk["path"])] = chunk
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


def _enacting_formula_start_in_records(
    records: list[tuple[int, float, str]], language: str, page_count: int
) -> tuple[int, str] | None:
    """Same signal as `_extract_chunks`'s `_enacting_formula_start`, rescanned over
    `_line_records`'s bbox-derived text instead of plain `page.get_text()` lines -
    an independent pass for the same reason `_extraction_accounting` never calls
    `_extract_chunks`: a mismatch between the two text modes must show up as a
    measurement discrepancy, not get silently papered over by sharing one result.
    Tries each line alone and joined with the one before it, and respects
    `ENACTING_FORMULA_MAX_PAGE_FRACTION`, same as `_enacting_formula_start`
    and for the same reasons.
    """
    pattern = _ENACTING_FORMULA_RE.get(language)
    if pattern is None:
        return None
    page_limit = max(ENACTING_FORMULA_MIN_PAGE_FLOOR, page_count * ENACTING_FORMULA_MAX_PAGE_FRACTION)
    previous = ""
    for page_number, _position, text in records:
        if page_number > page_limit:
            return None
        if pattern.search(text.upper()) or pattern.search(f"{previous} {text}".upper()):
            return page_number, text
        previous = text
    return None


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
    through to `unassigned` the way only its heading line still does. Front
    matter and the table of contents - everything before the enacting
    formula - land in `classified` the same way: named and accounted for,
    never a candidate, because `_extract_chunks` never lets them become one.
    """
    records = _line_records(pdf)
    furniture = _furniture_lines(records, pdf.page_count)
    boundaries = _division_boundaries(pdf)
    enacting_start = _enacting_formula_start_in_records(records, document.language, pdf.page_count)

    candidates: list[tuple[tuple[str, str], int, bool]] = []
    current_key: tuple[str, str] | None = None
    current_chars = 0
    current_lines = 0
    current_division = FRONT_MATTER_DIVISION if enacting_start is not None else BODY_DIVISION
    current_division_is_amendments = False
    current_division_max_token: tuple[int, str] | None = None
    previous_text = ""
    pdf_chars = 0
    unassigned_chars = 0
    classified_chars = 0

    for page_number, _position, text in records:
        pdf_chars += len(text)
        if current_division == FRONT_MATTER_DIVISION:
            classified_chars += len(text)
            if (page_number, text) == enacting_start:
                current_division = BODY_DIVISION
            previous_text = text
            continue
        headings = boundaries.get(page_number, frozenset())
        if text in headings:
            if current_key is not None:
                candidates.append((current_key, current_chars, _candidate_eligible(current_chars, current_lines)))
            current_division = text
            current_division_is_amendments = bool(_AMENDMENTS_DIVISION_RE.match(text.upper()))
            current_division_max_token = None
            current_key, current_chars, current_lines = (current_division, ""), 0, 0
            unassigned_chars += len(text)
            previous_text = text
            continue
        match = _SECTION_RE.match(text)
        match_is_inline = match is not None
        if match is None and not current_division_is_amendments:
            bare_match = _BARE_ITEM_RE.match(text)
            if current_division == BODY_DIVISION:
                if enacting_start is not None and bare_match and _looks_like_title(previous_text):
                    match = bare_match
            else:
                match = _SCHEDULE_ARTICLE_RE.match(text)
                if match is None and bare_match and not _ends_with_a_reference_word(previous_text):
                    match = bare_match
        if match is not None:
            token_key = _token_sort_key(match.group(1))
            if match_is_inline:
                current_division_max_token = token_key
            elif current_division_max_token is not None and token_key < current_division_max_token:
                match = None
            else:
                current_division_max_token = token_key
        if match:
            if current_key is not None:
                candidates.append((current_key, current_chars, _candidate_eligible(current_chars, current_lines)))
            current_key = (current_division, match.group(1))
            current_chars = len(text)
            current_lines = 1
            previous_text = text
            continue
        if current_key is not None:
            current_chars += len(text)
            current_lines += 1
            previous_text = text
            continue
        if text in furniture:
            classified_chars += len(text)
        else:
            unassigned_chars += len(text)
        previous_text = text
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


def _page_span_bucket(pages: int) -> str:
    """Which page-span band a chunk falls in, so a single 50-page blob (Act 512's
    schedules, kept whole by #89) shows up as an outlier instead of disappearing
    into a retention percentage."""
    if pages <= 1:
        return "1"
    if pages <= 5:
        return "2-5"
    if pages <= 20:
        return "6-20"
    if pages <= 50:
        return "21-50"
    return "51+"


def _chunk_quality(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-document chunk shape: which chunks are unnumbered blobs, and how big
    every chunk is.

    Reads `_extract_chunks`'s real output — the opposite of `_extraction_accounting`,
    which never touches it — so a blob that is a document's *entire* chunk set shows
    up here even though #89 correctly kept it. Since #95, every non-body chunk
    carries `section_number == ""` (a schedule item's number lives in `path`
    instead), so a blob is a non-body chunk whose `path` has no item segment:
    `None` (amendments) or `sched.<k>` with no `/para.`/`/art.` suffix.
    """
    blobs: list[dict[str, Any]] = []
    max_chars = 0
    max_pages = 0
    for chunk in chunks:
        chars = len(chunk["content"])
        pages = chunk["page_end"] - chunk["page_start"] + 1
        max_chars = max(max_chars, chars)
        max_pages = max(max_pages, pages)
        path = chunk.get("path")
        if chunk["division"] != BODY_DIVISION and (path is None or "/" not in path):
            blobs.append({
                "division": chunk["division"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "chars": chars,
            })
    return {
        "unnumbered_chunks": blobs,
        "max_chunk_chars": max_chars,
        "max_chunk_pages": max_pages,
    }


def diff_chunk_sets(
    old_chunks: Iterable[dict[str, Any]], new_chunks: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """What changed between two extraction generations of one document.

    Keyed by (division, path) — the same identity `_extract_chunks`'s own
    last-wins dedup already uses (ADR 0018) — so a real renumbering reads as one
    `changed` entry instead of an unrelated add/remove pair.
    """
    def sort_key(key: tuple[str, str | None]) -> tuple[str, str]:
        # `path` is None for an amendments-division chunk; sorting mixed None/str
        # raises TypeError, so it sorts as if it were the empty string instead.
        return (key[0], key[1] or "")

    old_by_key = {(c["division"], c["path"]): c for c in old_chunks}
    new_by_key = {(c["division"], c["path"]): c for c in new_chunks}
    added_keys = set(new_by_key) - set(old_by_key)
    removed_keys = set(old_by_key) - set(new_by_key)
    changed: list[dict[str, Any]] = []
    for key in sorted(set(old_by_key) & set(new_by_key), key=sort_key):
        old_chunk, new_chunk = old_by_key[key], new_by_key[key]
        if old_chunk["content_sha256"] == new_chunk["content_sha256"]:
            continue
        changed.append({
            "division": key[0],
            "path": key[1],
            "old_chars": len(old_chunk["content"]),
            "new_chars": len(new_chunk["content"]),
            "old_pages": [old_chunk["page_start"], old_chunk["page_end"]],
            "new_pages": [new_chunk["page_start"], new_chunk["page_end"]],
        })
    return {
        "added": [{"division": k[0], "path": k[1]} for k in sorted(added_keys, key=sort_key)],
        "removed": [{"division": k[0], "path": k[1]} for k in sorted(removed_keys, key=sort_key)],
        "changed": changed,
        "unchanged_count": len(set(old_by_key) & set(new_by_key)) - len(changed),
    }


def diff_extraction_manifests(
    old_manifest: dict[str, Any],
    new_manifest: dict[str, Any],
    *,
    old_extraction_root: Path,
    new_extraction_root: Path,
    document_ids: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """`diff_chunk_sets` for every document two manifests have in common.

    Reads each generation's bundle straight off disk by extraction_id, the same
    `{extraction_root}/{extraction_id}.chunks.json` path `extract_document` writes,
    so this works on any two `shadow-extract` runs, not just adjacent ones — the
    per-document form #76 needs to adjudicate what #93/#94 actually change.
    """
    def bundles_by_document(manifest: dict[str, Any], extraction_root: Path) -> dict[str, Path]:
        runs_by_document = {run["document_id"]: run["extraction_id"] for run in manifest["extraction_runs"]}
        return {
            document_id: Path(extraction_root) / f"{extraction_id}.chunks.json"
            for document_id, extraction_id in runs_by_document.items()
        }

    old_bundles = bundles_by_document(old_manifest, old_extraction_root)
    new_bundles = bundles_by_document(new_manifest, new_extraction_root)
    selected = set(document_ids) if document_ids else (set(old_bundles) & set(new_bundles))

    diffs: dict[str, dict[str, Any]] = {}
    for document_id in sorted(selected):
        old_path, new_path = old_bundles.get(document_id), new_bundles.get(document_id)
        if old_path is None or new_path is None or not old_path.exists() or not new_path.exists():
            continue
        old_chunks = json.loads(old_path.read_text(encoding="utf-8"))["chunks"]
        new_chunks = json.loads(new_path.read_text(encoding="utf-8"))["chunks"]
        diffs[document_id] = diff_chunk_sets(old_chunks, new_chunks)
    return diffs


# The AGC template's table-of-contents banner — present on an early page of 236 of
# a 250-document sample (94.4%). Not universal (a handful of short/older Acts lack
# it), so `chunk_looks_like_table_of_contents` also falls back to line shape below.
_TOC_HEADING_RE = re.compile(r"ARRANGEMENT OF (?:SECTIONS|CLAUSES)|SUSUNAN SEKSYEN")
# A bare item number with nothing after it on the same line — the shape a table of
# contents entry's number takes once PyMuPDF splits it from its title (#72).
# SECTION_PATTERN already refuses this shape, so a real heading's own line is never
# mistaken for one: `_extract_chunks` only ever keeps a numbered line with content on it.
_TOC_ROW_RE = re.compile(r"^\d{1,3}[A-Z]{0,2}\.$")


def chunk_looks_like_table_of_contents(content: str) -> bool:
    """A checker, never extractor logic — `_extract_chunks` never calls this.

    True if `content` is table-of-contents-shaped: the AGC banner, or enough bare
    item-number lines in a row that it reads as a list of headings rather than a
    section's own prose.
    """
    if _TOC_HEADING_RE.search(content.upper()):
        return True
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return False
    bare_number_lines = sum(1 for line in lines if _TOC_ROW_RE.match(line))
    return bare_number_lines >= 3 and bare_number_lines >= len(lines) / 4


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
    chunk_size_distribution: dict[str, int] = {}
    toc_chunks_scanned = 0
    toc_flagged: list[dict[str, str]] = []
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
        chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
        quality = _chunk_quality(chunks)
        for chunk in chunks:
            span = chunk["page_end"] - chunk["page_start"] + 1
            bucket = _page_span_bucket(span)
            chunk_size_distribution[bucket] = chunk_size_distribution.get(bucket, 0) + 1
            toc_chunks_scanned += 1
            if chunk_looks_like_table_of_contents(chunk["content"]):
                toc_flagged.append({
                    "document_id": identity,
                    "division": chunk["division"],
                    "section_number": chunk["section_number"],
                })
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
            **quality,
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
            "unnumbered_chunk_count": sum(len(item["unnumbered_chunks"]) for item in ready_results),
            "unnumbered_chunk_chars": sum(
                sum(blob["chars"] for blob in item["unnumbered_chunks"]) for item in ready_results
            ),
            "max_chunk_chars": max((item["max_chunk_chars"] for item in ready_results), default=0),
            "max_chunk_pages": max((item["max_chunk_pages"] for item in ready_results), default=0),
        },
        "chunk_size_distribution": chunk_size_distribution,
        "toc_oracle": {"chunks_scanned": toc_chunks_scanned, "flagged": toc_flagged},
    }
    return manifest, report
