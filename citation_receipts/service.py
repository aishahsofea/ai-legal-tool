"""Shared fail-closed availability checks for enrichment and delivery."""

from __future__ import annotations

import os

from corpus.models import CorpusDocument, ExtractionRun
from corpus.registry import CorpusDocumentIntegrityError, CorpusRegistry
from corpus.storage import configured_cdn_storage


def delivery_mode() -> str:
    mode = os.getenv("RECEIPT_DELIVERY_MODE", "auto").strip().lower()
    return mode if mode in {"auto", "local", "redirect", "proxy"} else "auto"


def validate_available(registry: CorpusRegistry, document: CorpusDocument):
    """Verify local bytes or remote object metadata before a receipt is exposed."""
    mode = delivery_mode()
    if mode in {"auto", "local"}:
        try:
            return "local", registry.validate(document)
        except CorpusDocumentIntegrityError:
            if mode == "local":
                raise
    storage = configured_cdn_storage()
    if storage is None:
        raise CorpusDocumentIntegrityError("No verified corpus delivery backend is available")
    storage.verify(document)
    return ("redirect" if mode in {"auto", "redirect"} else "proxy"), storage


def validate_coordinate_available(registry: CorpusRegistry, run: ExtractionRun):
    """Return a hash-verified local sidecar or a verified remote backend."""
    try:
        return "local", registry.validate_sidecar(run)
    except CorpusDocumentIntegrityError:
        storage = configured_cdn_storage()
        if storage is None:
            raise
        storage.verify_sidecar(run)
        return "remote", storage
