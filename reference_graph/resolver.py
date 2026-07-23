"""Mechanical resolver for explicit statutory references."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Provision
from .reference_lexer import ReferenceCandidate


@dataclass(frozen=True)
class Resolution:
    target_ids: list[str]
    reason_code: str | None = None


def _section_number(value: str) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,3}[A-Z]{0,2})\s*", value, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _numbers(body: str) -> list[str]:
    return list(dict.fromkeys(number.upper() for number in re.findall(r"\d{1,3}[A-Z]{0,2}", body, re.IGNORECASE)))


def _cross_act(phrase: str | None) -> str | None:
    if not phrase or phrase.casefold() == "this act":
        return None
    match = re.search(r"\[Act\s+(\d+)\]", phrase, re.IGNORECASE)
    return match.group(1) if match else None


def resolve(candidate: ReferenceCandidate, source: Provision, provisions: dict[str, Provision], act_number: str) -> Resolution:
    kind = candidate.kind.rstrip("s")
    cross_act = _cross_act(candidate.act_phrase)
    if cross_act and kind == "act":
        return Resolution([f"act:{cross_act}"])
    if cross_act and kind != "section":
        return Resolution([], "cross_act_non_section")
    if cross_act:
        targets = [f"act:{cross_act}/section:{number}" for number in _numbers(candidate.body)]
        return Resolution(targets or [], None if targets else "malformed_reference")
    if candidate.act_phrase and candidate.act_phrase.casefold() == "this act" and kind == "act":
        return Resolution([f"act:{act_number}"])

    if kind == "section":
        numbers = _numbers(candidate.body)
        if not numbers:
            return Resolution([], "malformed_reference")
        # Closed, numeric inclusive ranges only. Alphanumeric ranges are too ambiguous.
        range_match = re.fullmatch(r"\s*(\d+)\s*(?:to|–|-)\s*(\d+)\s*", candidate.body, re.IGNORECASE)
        if range_match:
            low, high = map(int, range_match.groups())
            if high < low or high - low > 200:
                return Resolution([], "malformed_range")
            numbers = [str(value) for value in range(low, high + 1)]
        targets = list(dict.fromkeys(f"act:{act_number}/section:{number}" for number in numbers))
    elif kind == "subsection":
        absolute_match = re.fullmatch(r"\s*(\d{1,3}[A-Z]{0,2})\s*\((\d+[A-Z]?)\)\s*", candidate.body, re.IGNORECASE)
        number_match = re.fullmatch(r"\s*\((\d+[A-Z]?)\)\s*", candidate.body, re.IGNORECASE)
        section_match = re.search(r"/section:([^/]+)", source.provision_id)
        if absolute_match:
            targets = [f"act:{act_number}/section:{absolute_match.group(1).upper()}/subsection:{absolute_match.group(2).upper()}"]
        elif number_match and section_match:
            targets = [f"act:{act_number}/section:{section_match.group(1)}/subsection:{number_match.group(1)}"]
        else:
            return Resolution([], "relative_context_missing")
    elif kind == "paragraph":
        labels = re.findall(r"\(([a-z]{1,3})\)", candidate.body, re.IGNORECASE)
        parent = source.provision_id
        if "/subparagraph:" in parent:
            parent = parent.rsplit("/paragraph:", 1)[0]
        elif "/paragraph:" in parent:
            parent = parent.rsplit("/paragraph:", 1)[0]
        if "/subsection:" not in parent or not labels:
            return Resolution([], "relative_context_missing")
        targets = [f"{parent}/paragraph:{label.lower()}" for label in labels]
    elif kind == "subparagraph":
        labels = re.findall(r"\(([ivxlcdm]+)\)", candidate.body, re.IGNORECASE)
        parent = source.provision_id.rsplit("/subparagraph:", 1)[0] if "/subparagraph:" in source.provision_id else source.provision_id
        if "/paragraph:" not in parent or not labels:
            return Resolution([], "relative_context_missing")
        targets = [f"{parent}/subparagraph:{label.lower()}" for label in labels]
    elif kind == "part":
        value = candidate.body.strip().lower().replace(" ", "")
        targets = [f"act:{act_number}/description:part-{value}"]
    elif kind == "schedule":
        value = candidate.body.strip().lower()
        targets = [f"act:{act_number}/schedule:{value}"]
    else:
        return Resolution([], "unsupported_reference_kind")
    missing = [target for target in targets if target not in provisions]
    if missing:
        return Resolution([], "target_not_indexed")
    return Resolution(targets)
