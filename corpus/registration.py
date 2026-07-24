"""Atomic registration of newly downloaded immutable PDF bytes."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import fitz

from corpus.identity import asset_key, document_id, sha256_file
from corpus.manifest import _timeline_for, source_language
from corpus.models import CorpusDocument


def _v2_manifest(raw: dict) -> dict:
    if raw.get("schema_version") == 2:
        return raw
    documents = []
    aliases = {}
    for item in raw.get("documents", []):
        identity = document_id(item["act_number"], item.get("language", "en"), item["sha256"])
        documents.append({
            "document_id": identity,
            "act_number": str(item["act_number"]),
            "act_title": str(item.get("act_title", "")),
            "language": str(item.get("language", "en")),
            "asset_key": asset_key(item["sha256"]),
            "sha256": item["sha256"],
            "byte_size": int(item["byte_size"]),
            "page_count": int(item["page_count"]),
            "source_url": str(item.get("source_url", "")),
            "timeline_date": str(item.get("timeline_date", "")),
            "timeline_type": str(item.get("timeline_type", "")),
            "metadata_scraped_at": str(item.get("metadata_scraped_at", "")),
            "lifecycle_status": "active",
            "document_kind": "reprint",
            "detail_url": "",
            "local_path": str(item.get("asset_path", "")),
        })
        aliases[str(item["document_id"])] = identity
    return {
        "schema_version": 2,
        "identity_algorithm": "sha256",
        "documents": documents,
        "extraction_runs": [],
        "active_documents": [],
        "aliases": aliases,
        "source_observations": [],
    }


def register_pdf(
    pdf_path: Path,
    *,
    metadata: dict,
    act_title: str,
    manifest_path: Path,
    asset_root: Path,
    source_url: str | None = None,
    timeline_date: str | None = None,
    timeline_type: str | None = None,
    language: str | None = None,
) -> CorpusDocument:
    """Copy exact bytes into content-addressed local storage and stage metadata.

    Registration never changes the active mapping. A new hash therefore cannot be
    retrieved until extraction, embedding, validation, and explicit activation.
    """
    pdf_path = Path(pdf_path)
    digest = sha256_file(pdf_path)
    with fitz.open(pdf_path) as pdf:
        if pdf.page_count < 1:
            raise ValueError("downloaded PDF has no pages")
        page_count = pdf.page_count
    with pdf_path.open("rb") as stream:
        signature = stream.read(5)
    if signature != b"%PDF-":
        raise ValueError("downloaded response is not a PDF")
    source_url = str(source_url or metadata.get("latest_reprint_pdf", ""))
    if not source_url:
        raise ValueError("base-Act registration requires a reprint source")
    language = language or source_language(metadata, source_url)
    identity = document_id(metadata["act_number"], language, digest)
    observed_date, observed_type = _timeline_for(metadata, source_url)
    timeline_date = str(timeline_date if timeline_date is not None else observed_date)
    timeline_type = str(timeline_type if timeline_type is not None else observed_type)
    if timeline_type not in {"REPRINT", "REPRINT ONLINE"}:
        raise ValueError("base-Act registration requires a consolidated snapshot")
    local_path = f"objects/sha256/{digest[:2]}/{digest[2:4]}/{digest}.pdf"
    destination = Path(asset_root) / local_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size != pdf_path.stat().st_size or sha256_file(destination) != digest:
            raise ValueError("content-addressed destination contains conflicting bytes")
    else:
        shutil.copyfile(pdf_path, destination)

    document = CorpusDocument(
        document_id=identity,
        act_number=str(metadata["act_number"]),
        act_title=act_title,
        language=language,
        asset_key=asset_key(digest),
        sha256=digest,
        byte_size=destination.stat().st_size,
        page_count=page_count,
        source_url=source_url,
        timeline_date=timeline_date,
        timeline_type=timeline_type,
        metadata_scraped_at=str(metadata.get("scraped_at", "")),
        lifecycle_status="registered",
        document_kind="reprint",
        detail_url=str(metadata.get("detail_url", "")),
        local_path=local_path,
    )
    try:
        raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {"schema_version": 2, "documents": []}
    manifest = _v2_manifest(raw)
    documents = {item["document_id"]: item for item in manifest.get("documents", [])}
    if identity in documents:
        document = CorpusDocument.from_dict(documents[identity])
    else:
        documents[identity] = document.to_dict()
    manifest["documents"] = [documents[key] for key in sorted(documents)]
    observations = manifest.setdefault("source_observations", [])
    observation = {
        "document_id": identity,
        "source_url": source_url,
        "observed_at": str(metadata.get("scraped_at", "")),
        "timeline_date": timeline_date,
        "timeline_type": timeline_type,
    }
    existing_observation = next(
        (
            item for item in observations
            if item.get("document_id") == identity
            and item.get("source_url") == source_url
            and item.get("observed_at") == observation["observed_at"]
        ),
        None,
    )
    if existing_observation is not None:
        if (
            existing_observation.get("timeline_date")
            and existing_observation["timeline_date"] != timeline_date
        ) or (
            existing_observation.get("timeline_type")
            and existing_observation["timeline_type"] != timeline_type
        ):
            raise ValueError("source observation timeline metadata conflicts")
        existing_observation.setdefault("timeline_date", timeline_date)
        existing_observation.setdefault("timeline_type", timeline_type)
    elif observation["observed_at"]:
        observations.append(observation)
        observations.sort(key=lambda item: (item["document_id"], item["source_url"], item["observed_at"]))
    Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="manifest-", suffix=".json", dir=Path(manifest_path).parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return document
