"""Local currency check for cited Acts.

Reads each cited Act's own metadata timeline; no network or model call.
Runs after grounding_check and only ever attaches a label beside an
already-validated citation, never edits one. Repeal takes priority over
everything else: a REPEALED/SUPERSEDED timeline entry means `repealed`
regardless of dates. Otherwise the latest AMENDMENTS date is compared
against the citation's own reprint date (`data/pdfs/manifest.json`'s
`timeline_date`) to tell `superseded` from `current_as_indexed`. Anything
that can't be compared -- no manifest match, no AMENDMENTS entry, an
unparseable date -- reads `unknown`.
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
MANIFEST_PATH = Path("data/pdfs/manifest.json")

# SUPERSEDED is a repeal by a differently-named instrument; same user-facing label.
_REPEAL_LOG_TYPES = {"REPEALED", "SUPERSEDED"}
_AMENDMENT_LOG_TYPE = "AMENDMENTS"
_DATE_FORMAT = "%d/%m/%Y"


def currency_check_enabled() -> bool:
    return flag_enabled("CURRENCY_CHECK_ENABLED")


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), _DATE_FORMAT)
    except ValueError:
        return None


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


def _select_latest_amendment_entry(timeline: list[dict]) -> dict | None:
    # Unlike repeal, an amendment's date is the whole signal here (it is what gets
    # compared against the reprint date), so an unparseable one can't fall back to
    # an arbitrary entry the way repeal does -- it can only drop out of contention.
    dated: list[tuple[datetime, dict]] = []
    for entry in timeline:
        if entry.get("log_type") != _AMENDMENT_LOG_TYPE:
            continue
        parsed = _parse_date(entry.get("date", ""))
        if parsed is not None:
            dated.append((parsed, entry))
    return max(dated, key=lambda item: item[0])[1] if dated else None


def _reprint_dates_by_document(manifest_path: Path | None = None) -> dict[str, str]:
    path = manifest_path if manifest_path is not None else MANIFEST_PATH
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(document["document_id"]): str(document.get("timeline_date", ""))
        for document in manifest.get("documents", [])
        if document.get("document_id")
    }


def _chunk_lookup(state: AgentState) -> dict[tuple[str, str], list[dict]]:
    lookup: dict[tuple[str, str], list[dict]] = {}
    for chunk in state.get("retrieved_chunks", []):
        key = canonicalize_citation_key(
            chunk.get("act_number"), chunk.get("section_number"), chunk.get("path")
        )
        lookup.setdefault(key, []).append(chunk)
    return lookup


def _label_for_act(
    display_act_number: str, canonical_act_number: str, language: str, reprint_date: str
) -> CurrencyLabel:
    path = metadata_path(METADATA_DIR, canonical_act_number)
    if not path.exists():
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    timeline = metadata.get("timeline_bm" if language == "bm" else "timeline")
    timeline = timeline if isinstance(timeline, list) else []

    repeal_entry = _select_repeal_entry(timeline)
    if repeal_entry is not None:
        return CurrencyLabel(
            act_number=display_act_number,
            label="repealed",
            detail_url=str(repeal_entry.get("pdf_url", "")),
            as_of_date=str(repeal_entry.get("date", "")),
        )

    reprint_parsed = _parse_date(reprint_date)
    amendment_entry = _select_latest_amendment_entry(timeline)
    amendment_parsed = _parse_date(amendment_entry.get("date", "")) if amendment_entry else None
    if reprint_parsed is None or amendment_parsed is None:
        return CurrencyLabel(act_number=display_act_number, label="unknown", detail_url="", as_of_date="")

    if amendment_parsed > reprint_parsed:
        return CurrencyLabel(
            act_number=display_act_number,
            label="superseded",
            detail_url=str(amendment_entry.get("pdf_url", "")),
            as_of_date=str(amendment_entry.get("date", "")),
        )

    return CurrencyLabel(act_number=display_act_number, label="current_as_indexed", detail_url="", as_of_date="")


def currency_check_node(state: AgentState) -> dict:
    if not currency_check_enabled():
        return {}

    try:
        chunks = _chunk_lookup(state)
        reprint_dates = _reprint_dates_by_document()
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
            chunk = matches[0] if matches else {}
            language = chunk.get("language", "en")
            reprint_date = reprint_dates.get(str(chunk.get("document_id", "")), "")

            labels.append(_label_for_act(act_number, canonical_act, language, reprint_date))

        return {"currency_labels": labels}
    except Exception:
        logger.warning("currency_check_node failed; skipping currency check", exc_info=True)
        return {}
