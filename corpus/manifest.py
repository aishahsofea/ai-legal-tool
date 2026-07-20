"""Deterministic corpus discovery, manifest generation, and per-PDF coverage."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import fitz

from corpus.identity import asset_key, document_id, sha256_file
from corpus.models import ActiveDocument, CorpusDocument, ExtractionRun

SCANNED_THRESHOLD = 100


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _title_map(index_path: Path) -> dict[str, dict[str, str]]:
    index = _json(index_path, {}) or {}
    result: dict[str, dict[str, str]] = {}
    for item in index.get("acts", []):
        act = str(item.get("act_number", ""))
        if not act:
            continue
        current = result.setdefault(act, {"title_en": "", "title_bm": ""})
        for key in ("title_en", "title_bm"):
            if not current[key] and item.get(key):
                current[key] = str(item[key]).strip()
    return result


def source_language(metadata: dict, source_url: str) -> str:
    """Derive source language from AGC's own URL/detail markers.

    This deliberately does not use the local directory name. BM-only PDFs were
    historically stored under ``pdfs/en`` and must remain BM sources.
    """
    marker = f"{metadata.get('detail_url', '')} {source_url}".lower()
    if "lang=bm" in marker or "/my/" in marker or "_bm/" in marker:
        return "bm"
    return "en"


def _timeline_for(metadata: dict, source_url: str) -> tuple[str, str]:
    for event in metadata.get("timeline", []):
        if str(event.get("pdf_url", "")) == source_url:
            return str(event.get("date", "")), str(event.get("log_type", ""))
    return "", ""


def _pdf_facts(path: Path) -> tuple[str, int, int, bool]:
    digest = sha256_file(path)
    byte_size = path.stat().st_size
    with fitz.open(path) as pdf:
        page_count = pdf.page_count
        characters = sum(len(page.get_text()) for page in pdf)
    scanned = characters / max(page_count, 1) < SCANNED_THRESHOLD
    return digest, byte_size, page_count, scanned


def _coverage_row(
    *,
    path: Path,
    document: CorpusDocument | None,
    status: str,
    reason: str,
    remediation: str,
    effort: str,
    fallback_url: str,
    requires_redownload: bool = False,
    requires_reextraction: bool = False,
) -> dict[str, Any]:
    return {
        "pdf": path.as_posix(),
        "act_number": document.act_number if document else path.stem,
        "document_id": document.document_id if document else "",
        "language": document.language if document else "",
        "status": status,
        "reason": reason,
        "remediation": remediation,
        "effort": effort,
        "requires_redownload": requires_redownload,
        "requires_reextraction": requires_reextraction,
        "fallback_url": fallback_url,
    }


def generate_manifest(
    *,
    pdf_root: Path,
    metadata_root: Path,
    index_path: Path,
    chunks_root: Path | None = None,
    existing_manifest: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Discover actual bytes and return deterministic manifest + coverage report."""
    pdf_root = Path(pdf_root).resolve()
    metadata_root = Path(metadata_root).resolve()
    titles = _title_map(index_path)
    previous = _json(existing_manifest, {}) if existing_manifest else {}
    previous = previous if isinstance(previous, dict) else {}

    previous_documents = {
        item.get("document_id"): item
        for item in previous.get("documents", [])
        if isinstance(item, dict) and item.get("document_id")
    }
    previous_extractions = {
        item.get("extraction_id"): item
        for item in previous.get("extraction_runs", [])
        if isinstance(item, dict) and item.get("extraction_id")
    }
    aliases = dict(previous.get("aliases", {})) if isinstance(previous.get("aliases", {}), dict) else {}
    old_active = previous.get("active_documents", []) if previous.get("schema_version") == 2 else []
    observations = {
        (
            str(item.get("document_id", "")),
            str(item.get("source_url", "")),
            str(item.get("observed_at", "")),
        ): {
            "document_id": str(item.get("document_id", "")),
            "source_url": str(item.get("source_url", "")),
            "observed_at": str(item.get("observed_at", "")),
        }
        for item in previous.get("source_observations", [])
        if (
            isinstance(item, dict)
            and item.get("document_id")
            and str(item.get("source_url", "")).startswith("https://")
            and item.get("observed_at")
        )
    }

    documents: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    pdf_files = sorted(pdf_root.rglob("*.pdf"), key=lambda path: path.relative_to(pdf_root).as_posix())

    for path in pdf_files:
        relative = path.relative_to(pdf_root).as_posix()
        act_number = path.stem
        metadata = _json(metadata_root / f"{act_number}.json", {}) or {}
        fallback_url = str(metadata.get("detail_url", ""))
        source_url = str(metadata.get("latest_reprint_pdf", ""))
        if not metadata:
            coverage.append(_coverage_row(
                path=Path(relative), document=None, status="blocked", reason="metadata_missing",
                remediation="Scrape authoritative Act metadata and register the PDF again.",
                effort="manual metadata repair", fallback_url="", requires_redownload=True,
            ))
            continue
        if not source_url:
            coverage.append(_coverage_row(
                path=Path(relative), document=None, status="blocked", reason="amendment_only",
                remediation="Remove the legacy base-Act chunks and obtain a consolidated reprint; never use the amendment PDF as the base Act.",
                effort="re-download and full re-extraction", fallback_url=fallback_url,
                requires_redownload=True, requires_reextraction=True,
            ))
            continue

        language = source_language(metadata, source_url)
        title = titles.get(act_number, {}).get(f"title_{language}", "")
        timeline_date, timeline_type = _timeline_for(metadata, source_url)
        try:
            digest, byte_size, page_count, scanned = _pdf_facts(path)
        except Exception:
            coverage.append(_coverage_row(
                path=Path(relative), document=None, status="blocked", reason="corrupt_pdf",
                remediation="Re-download from the recorded official source and register the new bytes.",
                effort="re-download and validation", fallback_url=fallback_url or source_url,
                requires_redownload=True, requires_reextraction=True,
            ))
            continue

        identity = document_id(act_number, language, digest)
        existing = previous_documents.get(identity, {})
        document = CorpusDocument(
            document_id=identity,
            act_number=act_number,
            act_title=title,
            language=language,
            asset_key=asset_key(digest),
            sha256=digest,
            byte_size=byte_size,
            page_count=page_count,
            source_url=source_url,
            timeline_date=timeline_date,
            timeline_type=timeline_type,
            metadata_scraped_at=str(metadata.get("scraped_at", "")),
            lifecycle_status=str(existing.get("lifecycle_status", "registered")),
            document_kind="reprint",
            detail_url=fallback_url,
            local_path=relative,
        )
        documents[identity] = document.to_dict()
        observed_at = str(metadata.get("scraped_at", ""))
        if observed_at:
            observation = {
                "document_id": identity,
                "source_url": source_url,
                "observed_at": observed_at,
            }
            observations[(identity, source_url, observed_at)] = observation

        if not title:
            coverage.append(_coverage_row(
                path=Path(relative), document=document, status="blocked", reason="title_missing",
                remediation=f"Add the authoritative {language.upper()} title to acts_index metadata and regenerate.",
                effort="metadata repair", fallback_url=fallback_url or source_url,
            ))
            continue
        if scanned:
            coverage.append(_coverage_row(
                path=Path(relative), document=document, status="blocked", reason="scanned_image_only",
                remediation="OCR the exact PDF, generate a coordinate sidecar, and run shadow extraction/embedding.",
                effort="OCR and full re-extraction", fallback_url=fallback_url or source_url,
                requires_reextraction=True,
            ))
            continue

        chunk_path = Path(chunks_root) / f"{act_number}.json" if chunks_root else None
        legacy_chunks = _json(chunk_path, None) if chunk_path else None
        matching_runs = [
            value for value in previous_extractions.values()
            if value.get("document_id") == identity and value.get("status") == "ready"
        ]
        active_identity = next(
            (item for item in old_active if item.get("document_id") == identity), None
        )
        if active_identity and matching_runs:
            status, reason = "enabled", "verified_active_extraction"
            remediation, effort = "None.", "none"
        elif matching_runs:
            status, reason = "ready", "verified_shadow_extraction"
            remediation, effort = "Validate embeddings and activate this Act/language mapping.", "operator activation"
        elif legacy_chunks is None:
            status, reason = "blocked", "not_extracted"
            remediation, effort = "Run shadow extraction, sidecar generation, embedding, and activation.", "full re-extraction"
        elif not legacy_chunks:
            status, reason = "blocked", "no_chunks"
            remediation, effort = "Repair extraction (or OCR), then embed and activate the verified extraction.", "extraction investigation"
        else:
            status, reason = "blocked", "legacy_chunks_without_provenance"
            remediation, effort = "Run full shadow extraction and re-embedding; do not infer provenance from the Act number.", "full re-extraction"
        coverage.append(_coverage_row(
            path=Path(relative), document=document, status=status, reason=reason,
            remediation=remediation, effort=effort, fallback_url=fallback_url or source_url,
            requires_reextraction=status not in {"enabled", "ready"},
        ))

    # Historical v2 documents remain addressable forever even when no longer current.
    if previous.get("schema_version") == 2:
        for identity, value in previous_documents.items():
            if identity not in documents:
                documents[identity] = {**value, "lifecycle_status": "superseded"}
    elif previous.get("schema_version") == 1:
        for item in previous.get("documents", []):
            digest = item.get("sha256", "")
            act = str(item.get("act_number", ""))
            language = str(item.get("language", "en"))
            target = document_id(act, language, digest)
            if target in documents:
                aliases[str(item["document_id"])] = target

    extraction_values = sorted(
        previous_extractions.values(), key=lambda item: str(item.get("extraction_id", ""))
    )
    valid_extraction_ids = {item.get("extraction_id") for item in extraction_values}
    active_values = sorted(
        (
            item for item in old_active
            if item.get("document_id") in documents and item.get("extraction_id") in valid_extraction_ids
        ),
        key=lambda item: (str(item.get("act_number", "")), str(item.get("language", ""))),
    )
    manifest = {
        "schema_version": 2,
        "identity_algorithm": "sha256",
        "documents": sorted(documents.values(), key=lambda item: item["document_id"]),
        "extraction_runs": extraction_values,
        "active_documents": active_values,
        "aliases": dict(sorted(aliases.items())),
        "source_observations": [
            observations[key]
            for key in sorted(observations)
            if observations[key]["document_id"] in documents
        ],
    }
    counts: dict[str, int] = {}
    for item in coverage:
        counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    report = {
        "schema_version": 1,
        "input_pdf_count": len(pdf_files),
        "registered_document_count": len(documents),
        "enabled_pdf_count": sum(item["status"] == "enabled" for item in coverage),
        "ready_pdf_count": sum(item["status"] == "ready" for item in coverage),
        "blocked_pdf_count": sum(item["status"] == "blocked" for item in coverage),
        "reason_counts": dict(sorted(counts.items())),
        "pdfs": coverage,
    }
    return manifest, report


def dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
