"""Immutable Citation Receipt documents and deterministic passage location."""

from citation_receipts.locator import LocatorResult, locate_evidence, normalized_tokens
from citation_receipts.registry import (
    ReceiptDocument,
    ReceiptDocumentIntegrityError,
    ReceiptDocumentNotFound,
    ReceiptManifestError,
    ReceiptRegistry,
    get_receipt_registry,
)

__all__ = [
    "LocatorResult",
    "ReceiptDocument",
    "ReceiptDocumentIntegrityError",
    "ReceiptDocumentNotFound",
    "ReceiptManifestError",
    "ReceiptRegistry",
    "get_receipt_registry",
    "locate_evidence",
    "normalized_tokens",
]
