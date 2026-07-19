"""Manifest-backed access to exact Receipt Document bytes.

Request values are resolved only through the manifest. Integrity is checked before
every use so a changed or missing asset can never be served as the approved snapshot.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = REPOSITORY_ROOT / "data" / "pdfs" / "manifest.json"


class ReceiptManifestError(RuntimeError):
    """The manifest itself is structurally invalid."""


class ReceiptDocumentNotFound(KeyError):
    """No manifest entry has the requested opaque document id."""


class ReceiptDocumentIntegrityError(RuntimeError):
    """A known Receipt Document does not match its manifest identity."""


@dataclass(frozen=True)
class ReceiptDocument:
    document_id: str
    act_number: str
    act_title: str
    language: str
    asset_path: str
    sha256: str
    byte_size: int
    page_count: int
    source_url: str
    timeline_date: str
    timeline_type: str
    metadata_scraped_at: str

    def public_metadata(self) -> dict[str, str]:
        return {
            "document_id": self.document_id,
            "act_number": self.act_number,
            "act_title": self.act_title,
            "timeline_date": self.timeline_date,
            "timeline_type": self.timeline_type,
            "sha256": self.sha256,
        }


class ReceiptRegistry:
    def __init__(self, manifest_path: Path = DEFAULT_MANIFEST_PATH):
        self.manifest_path = Path(manifest_path).resolve()
        self.asset_root = self.manifest_path.parent.resolve()
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReceiptManifestError("Receipt manifest could not be loaded") from exc

        if raw.get("schema_version") != 1 or not isinstance(raw.get("documents"), list):
            raise ReceiptManifestError("Unsupported or malformed Receipt manifest")

        documents: dict[str, ReceiptDocument] = {}
        acts: dict[str, ReceiptDocument] = {}
        required = set(ReceiptDocument.__dataclass_fields__)
        for item in raw["documents"]:
            if not isinstance(item, dict) or not required.issubset(item):
                raise ReceiptManifestError("Receipt manifest entry is incomplete")
            try:
                document = ReceiptDocument(**{key: item[key] for key in required})
            except (TypeError, ValueError) as exc:
                raise ReceiptManifestError("Receipt manifest entry is invalid") from exc
            if document.document_id in documents or document.act_number in acts:
                raise ReceiptManifestError("Receipt manifest contains duplicate identities")
            if len(document.sha256) != 64 or document.byte_size < 1 or document.page_count < 1:
                raise ReceiptManifestError("Receipt manifest identity metadata is invalid")
            self._resolve_asset_path(document)
            documents[document.document_id] = document
            acts[document.act_number] = document

        self.documents = documents
        self.documents_by_act = acts

    def _resolve_asset_path(self, document: ReceiptDocument) -> Path:
        relative = Path(document.asset_path)
        if relative.is_absolute():
            raise ReceiptManifestError("Receipt asset path must be relative")
        resolved = (self.asset_root / relative).resolve()
        try:
            resolved.relative_to(self.asset_root)
        except ValueError as exc:
            raise ReceiptManifestError("Receipt asset path escapes its manifest directory") from exc
        return resolved

    def get(self, document_id: str) -> ReceiptDocument:
        try:
            return self.documents[document_id]
        except KeyError as exc:
            raise ReceiptDocumentNotFound(document_id) from exc

    def for_act(self, act_number: object) -> ReceiptDocument | None:
        return self.documents_by_act.get(str(act_number or ""))

    def validate(self, document: ReceiptDocument) -> Path:
        path = self._resolve_asset_path(document)
        try:
            if not path.is_file() or path.stat().st_size != document.byte_size:
                raise ReceiptDocumentIntegrityError("Receipt Document size mismatch")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != document.sha256:
                raise ReceiptDocumentIntegrityError("Receipt Document hash mismatch")
            with fitz.open(path) as pdf:
                if pdf.page_count != document.page_count:
                    raise ReceiptDocumentIntegrityError("Receipt Document page-count mismatch")
        except ReceiptDocumentIntegrityError:
            logger.error("Receipt Document integrity check failed: %s", document.document_id)
            raise
        except Exception as exc:
            logger.error("Receipt Document could not be validated: %s", document.document_id)
            raise ReceiptDocumentIntegrityError("Receipt Document is unavailable") from exc
        return path

    def validated_for_act(self, act_number: object) -> ReceiptDocument | None:
        document = self.for_act(act_number)
        if document is None:
            return None
        try:
            self.validate(document)
        except ReceiptDocumentIntegrityError:
            return None
        return document


@lru_cache(maxsize=1)
def get_receipt_registry() -> ReceiptRegistry:
    return ReceiptRegistry()
