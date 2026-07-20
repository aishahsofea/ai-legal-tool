"""Validated data model for the deterministic corpus manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from corpus.identity import validate_asset_key, validate_language, validate_sha256

DocumentStatus = Literal["registered", "extracted", "active", "superseded", "blocked"]
ExtractionStatus = Literal["pending", "ready", "failed", "superseded"]


@dataclass(frozen=True)
class CoordinateSidecar:
    asset_key: str
    sha256: str
    byte_size: int
    format: str = "pymupdf-words-v1+gzip"
    local_path: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CoordinateSidecar":
        item = cls(
            asset_key=validate_asset_key(value["asset_key"]),
            sha256=validate_sha256(value["sha256"]),
            byte_size=int(value["byte_size"]),
            format=str(value.get("format", "pymupdf-words-v1+gzip")),
            local_path=str(value.get("local_path", "")),
        )
        if item.byte_size < 1:
            raise ValueError("coordinate sidecar byte_size must be positive")
        return item


@dataclass(frozen=True)
class CorpusDocument:
    document_id: str
    act_number: str
    act_title: str
    language: str
    asset_key: str
    sha256: str
    byte_size: int
    page_count: int
    source_url: str
    timeline_date: str
    timeline_type: str
    metadata_scraped_at: str
    lifecycle_status: DocumentStatus = "registered"
    document_kind: str = "reprint"
    detail_url: str = ""
    local_path: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CorpusDocument":
        item = cls(
            document_id=str(value["document_id"]),
            act_number=str(value["act_number"]),
            act_title=str(value.get("act_title", "")),
            language=validate_language(value["language"]),
            asset_key=validate_asset_key(value["asset_key"]),
            sha256=validate_sha256(value["sha256"]),
            byte_size=int(value["byte_size"]),
            page_count=int(value["page_count"]),
            source_url=str(value.get("source_url", "")),
            timeline_date=str(value.get("timeline_date", "")),
            timeline_type=str(value.get("timeline_type", "")),
            metadata_scraped_at=str(value.get("metadata_scraped_at", "")),
            lifecycle_status=str(value.get("lifecycle_status", "registered")),
            document_kind=str(value.get("document_kind", "reprint")),
            detail_url=str(value.get("detail_url", "")),
            local_path=str(value.get("local_path", "")),
        )
        if item.byte_size < 1 or item.page_count < 1:
            raise ValueError("document size and page count must be positive")
        if item.lifecycle_status not in {"registered", "extracted", "active", "superseded", "blocked"}:
            raise ValueError("invalid document lifecycle status")
        return item

    def public_metadata(self) -> dict[str, str]:
        return {
            "document_id": self.document_id,
            "act_number": self.act_number,
            "act_title": self.act_title,
            "language": self.language,
            "timeline_date": self.timeline_date,
            "timeline_type": self.timeline_type,
            "sha256": self.sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractionRun:
    extraction_id: str
    document_id: str
    extractor: str
    extractor_version: str
    configuration_hash: str
    chunk_set_hash: str
    chunk_count: int
    status: ExtractionStatus
    coordinate_sidecar: CoordinateSidecar | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExtractionRun":
        sidecar = value.get("coordinate_sidecar")
        item = cls(
            extraction_id=str(value["extraction_id"]),
            document_id=str(value["document_id"]),
            extractor=str(value["extractor"]),
            extractor_version=str(value["extractor_version"]),
            configuration_hash=validate_sha256(value["configuration_hash"]),
            chunk_set_hash=validate_sha256(value["chunk_set_hash"]),
            chunk_count=int(value["chunk_count"]),
            status=str(value["status"]),
            coordinate_sidecar=CoordinateSidecar.from_dict(sidecar) if sidecar else None,
        )
        if item.chunk_count < 0 or item.status not in {"pending", "ready", "failed", "superseded"}:
            raise ValueError("invalid extraction run status/count")
        if item.status == "ready" and (item.chunk_count < 1 or item.coordinate_sidecar is None):
            raise ValueError("ready extraction requires chunks and a coordinate sidecar")
        return item

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.coordinate_sidecar is None:
            value["coordinate_sidecar"] = None
        return value


@dataclass(frozen=True)
class ActiveDocument:
    act_number: str
    language: str
    document_id: str
    extraction_id: str
    previous_document_id: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActiveDocument":
        return cls(
            act_number=str(value["act_number"]),
            language=validate_language(value["language"]),
            document_id=str(value["document_id"]),
            extraction_id=str(value["extraction_id"]),
            previous_document_id=str(value.get("previous_document_id", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
