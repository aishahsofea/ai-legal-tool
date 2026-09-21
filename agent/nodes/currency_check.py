"""Local repeal check for cited Acts.

Reads each cited Act's own metadata timeline; no network or model call.
Runs after grounding_check and only ever attaches a label beside an
already-validated citation, never edits one. Only `repealed` is
distinguished from `unknown` for now -- `superseded` and
`current_as_indexed` need an amendment-date comparison not built yet, so
anything short of an outright repeal currently reads as `unknown`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from agent.citation_keys import canonicalize_act_number, canonicalize_citation_key
from agent.feature_flags import flag_enabled
from agent.state import AgentState, CurrencyLabel
from scraper.act_paths import metadata_path

logger = logging.getLogger(__name__)

METADATA_DIR = Path("data/acts_metadata")

# SUPERSEDED is a repeal by a differently-named instrument; same user-facing label.
_REPEAL_LOG_TYPES = {"REPEALED", "SUPERSEDED"}


def currency_check_enabled() -> bool:
    return flag_enabled("CURRENCY_CHECK_ENABLED")


def _select_repeal_entry(timeline: list[dict]) -> dict | None:
    repeal_entries = [entry for entry in timeline if entry.get("log_type") in _REPEAL_LOG_TYPES]
    if not repeal_entries:
        return None
    # A repeal entry's presence is the signal; an unparseable date must never
    # suppress detecting the repeal itself, only which entry's URL/date we surface.
    dated: list[tuple[datetime, dict]] = []
    for entry in repeal_entries:
        try:
            dated.append((datetime.strptime(str(entry.get("date", "")), "%d/%m/%Y"), entry))
        except ValueError:
            continue
    return max(dated, key=lambda item: item[0])[1] if dated else repeal_entries[0]


def _chunk_lookup(state: AgentState) -> dict[tuple[str, str], list[dict]]:
    lookup: dict[tuple[str, str], list[dict]] = {}
    for chunk in state.get("retrieved_chunks", []):
        key = canonicalize_citation_key(
            chunk.get("act_number"), chunk.get("section_number"), chunk.get("path")
        )
        lookup.setdefault(key, []).append(chunk)
    return lookup


def _label_for_act(display_act_number: str, canonical_act_number: str, language: str) -> CurrencyLabel:
    path = metadata_path(METADATA_DIR, canonical_act_number)
    if not path.exists():
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    timeline = metadata.get("timeline_bm" if language == "bm" else "timeline")
    entry = _select_repeal_entry(timeline if isinstance(timeline, list) else [])
    if entry is None:
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    return CurrencyLabel(
        act_number=display_act_number,
        label="repealed",
        detail_url=str(entry.get("pdf_url", "")),
        as_of_date=str(entry.get("date", "")),
    )


def currency_check_node(state: AgentState) -> dict:
    if not currency_check_enabled():
        return {}

    try:
        chunks = _chunk_lookup(state)
        labels: list[CurrencyLabel] = []
        seen: set[str] = set()

        for citation in state.get("citations", []):
            act_number = citation.get("act_number", "")
            canonical_act = canonicalize_act_number(act_number)
            if not canonical_act or canonical_act in seen:
                continue
            seen.add(canonical_act)

            key = canonicalize_citation_key(
                act_number, citation.get("section_number"), citation.get("path")
            )
            matches = chunks.get(key, [])
            language = matches[0].get("language", "en") if matches else "en"

            labels.append(_label_for_act(act_number, canonical_act, language))

        return {"currency_labels": labels}
    except Exception:
        logger.warning("currency_check_node failed; skipping currency check", exc_info=True)
        return {}
