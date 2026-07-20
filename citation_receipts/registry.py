"""Backward-compatible receipt façade over the immutable corpus registry."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from corpus.models import CorpusDocument as ReceiptDocument
from corpus.registry import (
    DEFAULT_MANIFEST_PATH,
    CorpusDocumentIntegrityError as ReceiptDocumentIntegrityError,
    CorpusDocumentNotFound as ReceiptDocumentNotFound,
    CorpusManifestError as ReceiptManifestError,
    CorpusRegistry,
)


class ReceiptRegistry(CorpusRegistry):
    """Compatibility name retained for saved links and downstream imports."""


@lru_cache(maxsize=1)
def get_receipt_registry() -> ReceiptRegistry:
    manifest = Path(os.getenv("CORPUS_MANIFEST_PATH", str(DEFAULT_MANIFEST_PATH)))
    return ReceiptRegistry(manifest)
