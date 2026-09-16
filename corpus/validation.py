"""Schema, byte, extraction, sidecar, and activation validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from corpus.extraction import EXTRACTOR_VERSION
from corpus.identity import asset_key
from corpus.registry import CorpusDocumentIntegrityError, CorpusManifestError, CorpusRegistry
from corpus.storage import CdnCorpusStorage


def validate_manifest(
    manifest_path: Path,
    *,
    asset_root: Path | None = None,
    sidecar_root: Path | None = None,
    cdn_base_url: str | None = None,
    scope: str = "full",
    deep: bool = False,
) -> dict[str, Any]:
    if scope not in {"registry", "active", "full"}:
        raise ValueError("scope must be registry, active, or full")
    errors: list[dict[str, str]] = []
    try:
        registry = CorpusRegistry(
            manifest_path, asset_root=asset_root, sidecar_root=sidecar_root
        )
    except CorpusManifestError as exc:
        return {
            "valid": False,
            "scope": scope,
            "document_count": 0,
            "extraction_count": 0,
            "active_count": 0,
            "errors": [{"code": "manifest_invalid", "detail": str(exc)}],
            "warnings": [],
        }

    documents = list(registry.documents.values())
    storage = CdnCorpusStorage(cdn_base_url) if cdn_base_url else None
    if scope == "active":
        active_ids = {item.document_id for item in registry.active_documents.values()}
        documents = [item for item in documents if item.document_id in active_ids]

    for document in documents:
        if document.asset_key != asset_key(document.sha256):
            errors.append({
                "code": "asset_key_mismatch",
                "document_id": document.document_id,
                "detail": "content-addressed asset key does not match SHA-256",
            })
        if scope == "registry":
            continue
        try:
            if storage is not None:
                storage.verify(document)
                if deep:
                    storage.deep_verify(document)
            else:
                registry.validate(document, deep=deep)
        except CorpusDocumentIntegrityError as exc:
            errors.append({
                "code": "document_integrity",
                "document_id": document.document_id,
                "detail": str(exc),
            })

    if scope in {"active", "full"}:
        extraction_ids = (
            {item.extraction_id for item in registry.active_documents.values()}
            if scope == "active"
            else set(registry.extraction_runs)
        )
        for identity in sorted(extraction_ids):
            run = registry.extraction_runs[identity]
            if run.status != "ready":
                continue
            try:
                if storage is not None:
                    storage.verify_sidecar(run)
                    if deep:
                        storage.get_sidecar(run)
                else:
                    registry.validate_sidecar(run, deep=deep)
            except CorpusDocumentIntegrityError as exc:
                errors.append({
                    "code": "sidecar_integrity",
                    "document_id": run.document_id,
                    "extraction_id": run.extraction_id,
                    "detail": str(exc),
                })

    warnings: list[dict[str, str]] = []
    active_versions = {
        registry.extraction_runs[mapping.extraction_id].extractor_version
        for mapping in registry.active_documents.values()
        if mapping.extraction_id in registry.extraction_runs
    }
    if active_versions and EXTRACTOR_VERSION not in active_versions:
        # #89: EXTRACTOR_VERSION drifted from what's active for five version bumps
        # (2.1.0 through 2.5.0) before anyone noticed, because nothing surfaced the
        # gap short of manually running extract_manifest and diffing by hand. A
        # non-fatal warning here means every `corpus validate` run says so instead.
        warnings.append({
            "code": "extractor_version_drift",
            "detail": (
                f"corpus/extraction.py computes EXTRACTOR_VERSION={EXTRACTOR_VERSION!r}, but the "
                f"manifest's active extraction runs use {sorted(active_versions)!r}. The database "
                "is serving an older extractor than main. Expected mid-rollout (shadow-extract "
                "ahead of activation) -- but the gap should be a decision someone keeps revisiting, "
                "not a fact nobody notices. See issue #89."
            ),
        })

    return {
        "valid": not errors,
        "scope": scope,
        "deep": deep,
        "backend": "cdn" if storage is not None else "local",
        "document_count": len(registry.documents),
        "validated_document_count": len(documents),
        "extraction_count": len(registry.extraction_runs),
        "active_count": len(registry.active_documents),
        "errors": errors,
        "warnings": warnings,
    }
