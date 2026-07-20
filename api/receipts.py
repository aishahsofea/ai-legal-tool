"""Verified receipt delivery, deterministic location, and browser telemetry."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from citation_receipts import (
    ReceiptDocumentIntegrityError,
    ReceiptDocumentNotFound,
    ReceiptManifestError,
    get_receipt_registry,
    locate_evidence,
    normalized_tokens,
)
from citation_receipts.service import validate_available, validate_coordinate_available
from citation_receipts.telemetry import record
from corpus.models import CorpusDocument, ExtractionRun

router = APIRouter(prefix="/receipts", tags=["receipts"])


class LocateRequest(BaseModel):
    evidence_quote: str | None = Field(default=None, max_length=500)
    start_page: int = Field(ge=1)
    extraction_id: str | None = Field(default=None, max_length=128)

    @field_validator("evidence_quote")
    @classmethod
    def _reject_empty_quote(cls, value: str | None) -> str | None:
        if value is not None and not normalized_tokens(value):
            raise ValueError("evidence_quote must contain at least one word")
        return value


class BrowserTelemetry(BaseModel):
    event: Literal[
        "locator_request_failed",
        "pdf_document_load_failed",
        "pdf_page_render_failed",
        "receipt_integrity_rejected",
    ]
    document_id: str = Field(min_length=1, max_length=160)
    stage: str = Field(default="", max_length=40)
    error_class: str = Field(default="", max_length=80)
    http_status: int | None = Field(default=None, ge=100, le=599)


def _document(document_id: str):
    try:
        registry = get_receipt_registry()
        return registry, registry.get(document_id)
    except ReceiptDocumentNotFound as exc:
        record("receipt_unavailable", document_id=document_id, reason="not_found")
        raise HTTPException(status_code=404, detail="Receipt Document not found") from exc
    except ReceiptManifestError as exc:
        record("receipt_unavailable", document_id=document_id, reason="manifest")
        raise HTTPException(status_code=503, detail="Citation Receipt service unavailable") from exc


def _available(registry, document):
    try:
        result = validate_available(registry, document)
        record("receipt_available", document_id=document.document_id, backend=result[0])
        return result
    except (ReceiptDocumentIntegrityError, ValueError) as exc:
        record("receipt_integrity_failure", document_id=document.document_id)
        raise HTTPException(status_code=503, detail="Receipt Document integrity check failed") from exc


def _immutable_headers(document: CorpusDocument) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": f'"{document.sha256}"',
        "Content-Disposition": f'inline; filename="act-{document.act_number}-{document.sha256[:12]}.pdf"',
        "X-Content-Type-Options": "nosniff",
    }


def _not_modified(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    return any(value.strip() in {"*", etag} for value in if_none_match.split(","))


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return None
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("unsupported range")
    start_value, separator, end_value = value[6:].partition("-")
    if not separator:
        raise ValueError("invalid range")
    if not start_value:
        suffix = int(end_value)
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        return max(0, size - suffix), size - 1
    start = int(start_value)
    end = int(end_value) if end_value else size - 1
    if start < 0 or start >= size or end < start:
        raise ValueError("unsatisfiable range")
    return start, min(end, size - 1)


def _file_blocks(path: Path, start: int, end: int, block_size: int = 1024 * 1024) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as stream:
        stream.seek(start)
        while remaining:
            block = stream.read(min(block_size, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def _local_response(
    path: Path,
    document: CorpusDocument,
    *,
    method: str,
    range_header: str | None,
    if_range: str | None,
) -> Response:
    headers = _immutable_headers(document)
    etag = headers["ETag"]
    if if_range and if_range != etag:
        range_header = None
    try:
        selected = _parse_range(range_header, document.byte_size)
    except (ValueError, TypeError):
        headers["Content-Range"] = f"bytes */{document.byte_size}"
        return Response(status_code=416, headers=headers)
    start, end = selected or (0, document.byte_size - 1)
    length = end - start + 1
    headers["Content-Length"] = str(length)
    status = 206 if selected else 200
    if selected:
        headers["Content-Range"] = f"bytes {start}-{end}/{document.byte_size}"
    if method == "HEAD":
        return Response(status_code=status, media_type="application/pdf", headers=headers)
    return StreamingResponse(
        _file_blocks(path, start, end), status_code=status,
        media_type="application/pdf", headers=headers,
    )


def _remote_proxy_response(storage, document: CorpusDocument, method: str, range_header: str | None):
    headers = _immutable_headers(document)
    if method == "HEAD":
        headers["Content-Length"] = str(document.byte_size)
        return Response(status_code=200, media_type="application/pdf", headers=headers)
    try:
        upstream = storage.get(document, range_header)
    except ReceiptDocumentIntegrityError as exc:
        record("receipt_delivery_failure", document_id=document.document_id, backend="proxy")
        raise HTTPException(status_code=503, detail="Receipt Document delivery failed") from exc
    for name in ("Content-Length", "Content-Range"):
        if upstream.headers.get(name):
            headers[name] = upstream.headers[name]

    def blocks():
        try:
            yield from upstream.iter_content(1024 * 1024)
        finally:
            upstream.close()

    return StreamingResponse(
        blocks(), status_code=upstream.status_code,
        media_type="application/pdf", headers=headers,
    )


def _deliver(
    document_id: str,
    request: Request,
    if_none_match: str | None,
    range_header: str | None,
    if_range: str | None,
):
    registry, document = _document(document_id)
    backend, resource = _available(registry, document)
    headers = _immutable_headers(document)
    if _not_modified(if_none_match, headers["ETag"]):
        return Response(status_code=304, headers=headers)
    if backend == "redirect":
        headers["Content-Length"] = "0"
        return RedirectResponse(resource.url(document), status_code=307, headers=headers)
    if backend == "proxy":
        return _remote_proxy_response(resource, document, request.method, range_header)
    return _local_response(
        resource, document, method=request.method,
        range_header=range_header, if_range=if_range,
    )


@router.api_route("/{document_id}/pdf", methods=["GET", "HEAD"])
def receipt_pdf(
    document_id: str,
    request: Request,
    if_none_match: str | None = Header(default=None),
    range_header: str | None = Header(default=None, alias="Range"),
    if_range: str | None = Header(default=None),
):
    return _deliver(document_id, request, if_none_match, range_header, if_range)


def _locator_extraction(registry, document, requested: str | None) -> ExtractionRun | None:
    if requested:
        return registry.validate_exact_extraction(document, requested)
    if registry.schema_version == 1:
        return None
    run = registry.active_extraction(document)
    if run is None:
        raise ReceiptDocumentIntegrityError("Receipt coordinate extraction is unavailable")
    return run


@router.post("/{document_id}/locate")
def locate_receipt_evidence(document_id: str, request: LocateRequest):
    registry, document = _document(document_id)
    backend, resource = _available(registry, document)
    if request.start_page > document.page_count:
        raise HTTPException(status_code=422, detail=f"start_page must be between 1 and {document.page_count}")
    try:
        extraction = _locator_extraction(registry, document, request.extraction_id)
        coordinate_backend, coordinate_resource = (
            validate_coordinate_available(registry, extraction)
            if extraction else ("legacy", None)
        )
        sidecar = coordinate_resource if coordinate_backend == "local" else None
        sidecar_bytes = (
            coordinate_resource.get_sidecar(extraction)
            if coordinate_backend == "remote" else None
        )
        if backend != "local":
            # Locator requires the verified local PDF only for v1 fallback. V2 runs
            # operate entirely from a hash-verified sidecar.
            if sidecar is None and sidecar_bytes is None:
                raise ReceiptDocumentIntegrityError("Legacy locator requires local PDF bytes")
            pdf_path = Path(".")
        else:
            pdf_path = resource
        result = locate_evidence(
            pdf_path, request.evidence_quote, request.start_page,
            sidecar_path=sidecar,
            sidecar_bytes=sidecar_bytes,
            document_id=document.document_id,
            document_sha256=document.sha256,
        )
    except (ReceiptDocumentIntegrityError, ValueError) as exc:
        record("locator_unavailable", document_id=document.document_id)
        raise HTTPException(status_code=503, detail="Receipt locator integrity check failed") from exc
    record(
        "locator_outcome", document_id=document.document_id,
        extraction_id=extraction.extraction_id if extraction else "legacy-v1",
        status=result.status,
    )
    metadata = document.public_metadata()
    metadata["document_id"] = document_id
    return {
        "status": result.status,
        "fallback_page": result.fallback_page,
        "document": metadata,
        "pages": [asdict(page) for page in result.pages],
    }


@router.post("/telemetry", status_code=202)
def receipt_browser_telemetry(payload: BrowserTelemetry):
    record(
        "frontend_receipt_failure", event_name=payload.event,
        document_id=payload.document_id, stage=payload.stage,
        error_class=payload.error_class, http_status=payload.http_status,
    )
    return {"accepted": True}
