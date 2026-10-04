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
    """Sentences naming an Act or section, plus same-paragraph follow-ons, as draft slices."""
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
    """The one cited source a claim rests on, or None when uncertain."""
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
