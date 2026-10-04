"""Deterministic claim extraction for the Jev first pass (#201).

Mirrors the attribution rule in `grounding_check._SYSTEM`: only a sentence that
names an Act or section is a claim. Over-keeping is safe, because an extra claim
only gives Jev one more sentence to clear. Dropping a real claim is the failure
that matters, since a claim that is never extracted is never checked once Ultra is
skipped. Every returned claim is a slice of the draft, so it always passes
`contains_normalized_sequence(claim, draft)`.
"""
from __future__ import annotations

import re

from agent.citation_keys import canonicalize_section_number

# A dot after one of these ends no sentence: "s. 90A", "Sdn. Bhd.", "No. 5".
_ABBREVIATIONS = (
    "s", "ss", "sub-s", "cl", "para", "art", "no", "nos", "cap", "pt", "sch", "r", "reg",
    "v", "vs", "dr", "sdn", "bhd", "ltd", "bil", "ms", "mr", "mrs", "e.g", "i.e", "etc",
)
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]*[A-Z0-9])|\n+")
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]+|\d{1,2}[.)])\s+")
_ABBREVIATION_END = re.compile(
    r"(?:^|[\s(\[])(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")\.$", re.IGNORECASE
)

# English and BM: "section 90A", "subsection (2)", "seksyen 13", "the Act", "Akta Syarikat".
_ATTRIBUTION = re.compile(
    r"\b(?:sub-?sections?|sections?|seksyen|subseksyen|ss?\.)\s*\(?\d"
    r"|\b(?:Act|Akta)\b",
    re.IGNORECASE,
)


def _sentences(draft: str) -> list[tuple[str, bool]]:
    """(sentence, shares a paragraph with the one before it)."""
    pieces: list[tuple[str, bool]] = []
    start = 0
    same_paragraph = False
    for match in _BOUNDARY.finditer(draft):
        if _ABBREVIATION_END.search(draft[start:match.start()].rstrip()):
            continue
        pieces.append((draft[start:match.start()], same_paragraph))
        same_paragraph = "\n" not in match.group()
        start = match.end()
    pieces.append((draft[start:], same_paragraph))
    return pieces


def split_claims(draft: str) -> list[str]:
    """Sentences naming an Act or section, plus the unattributed ones that follow them.

    Ultra extracts a sentence like "That permission is subject to a Minister" as a
    claim even though it names nothing (measured in #201), so a same-paragraph
    sentence after a claim is kept too. Disclaimers sit after a paragraph break.
    """
    claims = []
    previous_kept = False
    for piece, same_paragraph in _sentences(draft):
        sentence = _LIST_MARKER.sub("", piece).strip()
        previous_kept = bool(sentence) and (
            bool(_ATTRIBUTION.search(sentence)) or (previous_kept and same_paragraph)
        )
        if previous_kept:
            claims.append(sentence)
    return claims


_SECTION_MENTION = re.compile(
    r"\b(?:sub-?sections?|sections?|seksyen|subseksyen|ss?\.)\s*(\d+[A-Za-z]{0,2})\b", re.IGNORECASE
)


def pair_source(claim: str, sources: list[dict]) -> dict | None:
    """The one cited source a claim rests on, or None when that is not certain.

    Ultra returns the Act and section per claim; a sentence has to be read for
    them. None sends the claim to Ultra rather than guessing, because Jev scored
    against the wrong section would be a confident answer to the wrong question.
    """
    mentioned = {canonicalize_section_number(m) for m in _SECTION_MENTION.findall(claim)}
    candidates = [
        s for s in sources
        if canonicalize_section_number(s.get("section_number")) in mentioned
    ] if mentioned else list(sources)
    if len(candidates) > 1:
        lowered = claim.lower()
        named = [
            s for s in candidates
            if (s.get("act_title") or "").lower() in lowered
            or re.search(rf"\bAct\s+{re.escape(str(s.get('act_number')))}\b", claim, re.IGNORECASE)
        ]
        candidates = named
    return candidates[0] if len(candidates) == 1 else None
