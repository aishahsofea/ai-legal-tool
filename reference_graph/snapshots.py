"""Strict catalog and explicit immutable acquisition for consolidated snapshots."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import fitz
import requests

from corpus.manifest import source_language
from corpus.registration import register_pdf
from corpus.registry import CorpusDocumentIntegrityError, CorpusRegistry

CONSOLIDATED_TYPES = frozenset({"REPRINT", "REPRINT ONLINE"})
TEXT_CHARACTERS_PER_PAGE_MINIMUM = 100
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class SnapshotCatalogError(ValueError):
    """The recorded timeline cannot be interpreted without guessing."""


class SnapshotUnavailable(RuntimeError):
    """The authoritative source bytes could not be reached."""


class SnapshotIntegrityError(RuntimeError):
    """Downloaded bytes are not a parseable PDF."""


@dataclass(frozen=True)
class SnapshotCatalogEntry:
    act_number: str
    language: str
    snapshot_date: str
    source_date: str
    snapshot_type: str
    project_id: str
    source_url: str
    registered_document_id: str = ""
    graph_document_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _strict_date(value: object) -> date:
    raw = str(value)
    try:
        parsed = datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError as exc:
        raise SnapshotCatalogError(f"invalid_snapshot_date:{raw}") from exc
    if parsed.strftime("%d/%m/%Y") != raw:
        raise SnapshotCatalogError(f"invalid_snapshot_date:{raw}")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotCatalogError(f"catalog_unreadable:{Path(path).name}") from exc
    if not isinstance(value, dict):
        raise SnapshotCatalogError("catalog_not_object")
    return value


def _registered_sources(registry: CorpusRegistry) -> dict[str, str]:
    sources = {
        document.source_url: document.document_id
        for document in registry.documents.values()
        if document.source_url
    }
    for observation in registry.source_observations:
        sources[observation["source_url"]] = observation["document_id"]
    return sources


def _preferred_graph_ids(registry: CorpusRegistry) -> dict[str, str]:
    """Preserve historical graph aliases while using content IDs for new snapshots."""
    aliases_by_target: dict[str, list[str]] = {}
    for alias, target in registry.aliases.items():
        aliases_by_target.setdefault(target, []).append(alias)
    return {
        document_id: sorted(aliases_by_target.get(document_id, [document_id]))[0]
        for document_id in registry.documents
    }


def catalog_snapshots(
    metadata_path: Path,
    manifest_path: Path,
    *,
    asset_root: Path | None = None,
) -> list[SnapshotCatalogEntry]:
    """Return eligible recorded snapshots in strict chronological order, offline."""
    metadata = _load_json(metadata_path)
    act_number = str(metadata.get("act_number", ""))
    if not act_number:
        raise SnapshotCatalogError("catalog_act_number_missing")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root)
    sources = _registered_sources(registry)
    graph_ids = _preferred_graph_ids(registry)
    rows: list[tuple[date, SnapshotCatalogEntry]] = []
    seen: set[tuple[date, str, str]] = set()
    for raw in metadata.get("timeline", []):
        if not isinstance(raw, dict) or raw.get("log_type") not in CONSOLIDATED_TYPES:
            continue
        parsed = _strict_date(raw.get("date"))
        source_url = str(raw.get("pdf_url", ""))
        if not source_url.startswith("https://"):
            raise SnapshotCatalogError(f"invalid_snapshot_url:{raw.get('date', '')}")
        key = (parsed, str(raw["log_type"]), source_url)
        if key in seen:
            raise SnapshotCatalogError(f"duplicate_snapshot:{raw.get('date', '')}")
        seen.add(key)
        registered = sources.get(source_url, "")
        entry = SnapshotCatalogEntry(
            act_number=act_number,
            language=source_language(metadata, source_url),
            snapshot_date=parsed.isoformat(),
            source_date=str(raw["date"]),
            snapshot_type=str(raw["log_type"]),
            project_id=str(raw.get("project_id", "")),
            source_url=source_url,
            registered_document_id=registered,
            graph_document_id=graph_ids.get(registered, registered),
        )
        rows.append((parsed, entry))
    return [entry for _parsed, entry in sorted(rows, key=lambda item: (item[0], item[1].source_url))]


def catalog_report(entries: Iterable[SnapshotCatalogEntry]) -> dict[str, Any]:
    snapshots = [entry.to_dict() for entry in entries]
    return {
        "status": "catalogued",
        "network_used": False,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }


def _validate_pdf(path: Path) -> tuple[int, int, bool]:
    try:
        with Path(path).open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise SnapshotIntegrityError("response_is_not_pdf")
        with fitz.open(path) as pdf:
            page_count = pdf.page_count
            characters = sum(len(page.get_text()) for page in pdf)
    except SnapshotIntegrityError:
        raise
    except Exception as exc:
        raise SnapshotIntegrityError("pdf_unreadable") from exc
    if page_count < 1:
        raise SnapshotIntegrityError("pdf_has_no_pages")
    scanned = characters / page_count < TEXT_CHARACTERS_PER_PAGE_MINIMUM
    return page_count, characters, scanned


def _download(
    session: requests.Session,
    entry: SnapshotCatalogEntry,
    destination: Path,
    *,
    timeout: tuple[float, float] = (10.0, 90.0),
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = destination.stat().st_size if destination.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    try:
        response = session.get(entry.source_url, headers=headers, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        raise SnapshotUnavailable(type(exc).__name__) from exc
    try:
        if response.status_code == 416 and existing:
            return destination
        if response.status_code not in {200, 206}:
            raise SnapshotUnavailable(f"http_{response.status_code}")
        append = response.status_code == 206 and existing > 0
        mode = "ab" if append else "wb"
        with destination.open(mode) as stream:
            for chunk in response.iter_content(DOWNLOAD_CHUNK_SIZE):
                if chunk:
                    stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
    except requests.RequestException as exc:
        raise SnapshotUnavailable(type(exc).__name__) from exc
    finally:
        response.close()
    return destination


def _report_row(
    entry: SnapshotCatalogEntry,
    *,
    acquisition_status: str,
    readiness_status: str,
    document_id: str = "",
    sha256: str = "",
    byte_size: int = 0,
    page_count: int = 0,
    local_path: str = "",
    reason: str = "",
) -> dict[str, Any]:
    return {
        **entry.to_dict(),
        "registered_document_id": entry.registered_document_id or document_id,
        "graph_document_id": entry.graph_document_id or document_id,
        "acquisition_status": acquisition_status,
        "readiness_status": readiness_status,
        "document_id": document_id,
        "sha256": sha256,
        "byte_size": byte_size,
        "page_count": page_count,
        "local_path": local_path,
        "receipt_path": f"/receipts/{document_id}/pdf" if document_id else "",
        "reason": reason,
    }


def acquire_snapshots(
    entries: Iterable[SnapshotCatalogEntry],
    *,
    metadata_path: Path,
    manifest_path: Path,
    asset_root: Path,
    staging_root: Path,
    act_title: str,
    selected_dates: set[str] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Explicitly download/register selected sources without activating research data."""
    metadata = _load_json(metadata_path)
    before = _load_json(manifest_path).get("active_documents", [])
    client = session or requests.Session()
    rows: list[dict[str, Any]] = []
    try:
        for entry in entries:
            if selected_dates is not None and entry.snapshot_date not in selected_dates:
                continue
            if entry.registered_document_id:
                registry = CorpusRegistry(manifest_path, asset_root=asset_root)
                document = registry.get(entry.registered_document_id)
                try:
                    registered_path = registry.validate(document)
                    _page_count, _characters, scanned = _validate_pdf(registered_path)
                    rows.append(_report_row(
                        entry,
                        acquisition_status="already_registered",
                        readiness_status="scanned_unparseable" if scanned else "ready",
                        document_id=document.document_id,
                        sha256=document.sha256,
                        byte_size=document.byte_size,
                        page_count=document.page_count,
                        local_path=document.local_path,
                        reason="text_layer_below_threshold" if scanned else "",
                    ))
                except (CorpusDocumentIntegrityError, SnapshotIntegrityError) as exc:
                    rows.append(_report_row(
                        entry,
                        acquisition_status="integrity_failure",
                        readiness_status="blocked",
                        document_id=document.document_id,
                        sha256=document.sha256,
                        byte_size=document.byte_size,
                        page_count=document.page_count,
                        local_path=document.local_path,
                        reason=str(exc),
                    ))
                continue
            staged = (
                Path(staging_root)
                / f"act-{entry.act_number}-{entry.snapshot_date}-{entry.project_id or 'unknown'}.pdf.part"
            )
            try:
                _download(client, entry, staged)
                page_count, _characters, scanned = _validate_pdf(staged)
                document = register_pdf(
                    staged,
                    metadata=metadata,
                    act_title=act_title,
                    manifest_path=manifest_path,
                    asset_root=asset_root,
                    source_url=entry.source_url,
                    timeline_date=entry.source_date,
                    timeline_type=entry.snapshot_type,
                    language=entry.language,
                )
                rows.append(_report_row(
                    entry,
                    acquisition_status="downloaded",
                    readiness_status="scanned_unparseable" if scanned else "ready",
                    document_id=document.document_id,
                    sha256=document.sha256,
                    byte_size=document.byte_size,
                    page_count=page_count,
                    local_path=document.local_path,
                    reason="text_layer_below_threshold" if scanned else "",
                ))
            except SnapshotUnavailable as exc:
                rows.append(_report_row(
                    entry,
                    acquisition_status="unavailable",
                    readiness_status="blocked",
                    reason=str(exc),
                ))
            except SnapshotIntegrityError as exc:
                staged.unlink(missing_ok=True)
                rows.append(_report_row(
                    entry,
                    acquisition_status="integrity_failure",
                    readiness_status="blocked",
                    reason=str(exc),
                ))
    finally:
        if session is None:
            client.close()
    after = _load_json(manifest_path).get("active_documents", [])
    if before != after:
        raise RuntimeError("snapshot_acquisition_changed_active_documents")
    return {
        "status": "acquisition_complete",
        "network_used": True,
        "active_documents_unchanged": True,
        "snapshots": rows,
    }


def write_report(path: Path, report: dict[str, Any]) -> Path:
    """Atomically persist a deterministic operator report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="snapshot-report-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
