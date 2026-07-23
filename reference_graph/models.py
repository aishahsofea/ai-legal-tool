"""Typed, JSON-safe records used by the reference-graph pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal

GRAPH_SCHEMA_VERSION = 1
GRAPH_DOCUMENT_ID = "act-265-reprint-2023-6fec2f07"
PROVISION_KINDS = {
    "act", "section", "subsection", "paragraph", "subparagraph", "schedule", "description",
}


def versioned_id(document_id: str, provision_id: str) -> str:
    """Return a version-qualified identity without changing the readable identity."""
    return f"{document_id}/provision:{provision_id}"


def stable_id(act_number: str, *parts: tuple[str, str]) -> str:
    return "/".join([f"act:{act_number}", *(f"{kind}:{value}" for kind, value in parts)])


@dataclass(frozen=True)
class Rectangle:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class PageProvenance:
    page_number: int
    rectangles: list[Rectangle]


@dataclass(frozen=True)
class Evidence:
    """An exact literal span. Offsets are zero-based and end-exclusive."""

    text: str
    start_offset: int
    end_offset: int
    pages: list[PageProvenance]


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    corpus_document_id: str
    act_number: str
    act_title: str
    language: str
    sha256: str
    page_count: int
    receipt_path: str
    pdf_path: str
    manifest_path: str


@dataclass(frozen=True)
class Provision:
    provision_id: str
    version_id: str
    kind: Literal["act", "section", "subsection", "paragraph", "subparagraph", "schedule", "description"]
    label: str
    parent_id: str | None
    text: str
    start_offset: int
    end_offset: int
    page_start: int
    page_end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source_provision_id: str
    source_version_id: str
    target_provision_id: str
    target_version_id: str | None
    relationship: str
    reference_kind: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UnresolvedReference:
    candidate_id: str
    source_provision_id: str
    source_version_id: str
    literal: str
    reference_kind: str
    reason_code: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    source_provision_id: str
    source_version_id: str
    literal: str
    reference_kind: str
    target_provision_ids: list[str]
    resolution: str
    reason_code: str | None
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def candidate_id(source_id: str, start_offset: int, literal: str) -> str:
    digest = sha256(f"{source_id}:{start_offset}:{literal}".encode("utf-8")).hexdigest()[:16]
    return f"candidate:{digest}"


def edge_id(source_id: str, target_id: str, start_offset: int, literal: str) -> str:
    digest = sha256(f"{source_id}:{target_id}:{start_offset}:{literal}".encode("utf-8")).hexdigest()[:16]
    return f"edge:{digest}"
