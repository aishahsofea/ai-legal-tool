"""Citation Receipt PDF delivery and deterministic Evidence Span location."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from citation_receipts import (
    ReceiptDocumentIntegrityError,
    ReceiptDocumentNotFound,
    ReceiptManifestError,
    get_receipt_registry,
    locate_evidence,
    normalized_tokens,
)

router = APIRouter(prefix="/receipts", tags=["receipts"])


class LocateRequest(BaseModel):
    evidence_quote: str | None = Field(default=None, max_length=500)
    start_page: int = Field(ge=1)

    @field_validator("evidence_quote")
    @classmethod
    def _reject_empty_quote(cls, value: str | None) -> str | None:
        if value is not None and not normalized_tokens(value):
            raise ValueError("evidence_quote must contain at least one word")
        return value


def _document(document_id: str):
    try:
        registry = get_receipt_registry()
        return registry, registry.get(document_id)
    except ReceiptDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Receipt Document not found") from exc
    except ReceiptManifestError as exc:
        raise HTTPException(status_code=503, detail="Citation Receipt service unavailable") from exc


def _validated_path(registry, document):
    try:
        return registry.validate(document)
    except ReceiptDocumentIntegrityError as exc:
        raise HTTPException(status_code=503, detail="Receipt Document integrity check failed") from exc


@router.get("/{document_id}/pdf")
def get_receipt_pdf(document_id: str):
    registry, document = _document(document_id)
    path = _validated_path(registry, document)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"act-{document.act_number}-{document.sha256[:8]}.pdf",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{document.sha256}"',
        },
    )


@router.post("/{document_id}/locate")
def locate_receipt_evidence(document_id: str, request: LocateRequest):
    registry, document = _document(document_id)
    path = _validated_path(registry, document)
    if request.start_page > document.page_count:
        raise HTTPException(
            status_code=422,
            detail=f"start_page must be between 1 and {document.page_count}",
        )
    result = locate_evidence(path, request.evidence_quote, request.start_page)
    return {
        "status": result.status,
        "fallback_page": result.fallback_page,
        "document": document.public_metadata(),
        "pages": [asdict(page) for page in result.pages],
    }
