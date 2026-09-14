"""Boot-time report of how much of the registry a deployment can actually serve."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from corpus.registry import CorpusRegistry
from corpus.storage import CdnCorpusStorage

logger = logging.getLogger(__name__)

# A boot probe runs one HEAD per active document, so a dead bucket would
# otherwise hold up the health check for as long as the active set is long.
# The wall-clock budget is what bounds that: the per-request timeout alone
# still multiplies by the number of documents.
PROBE_TIMEOUT_SECONDS = 2.0
PROBE_BUDGET_SECONDS = 5.0


@dataclass(frozen=True)
class ReceiptCoverage:
    registered: int
    registered_local: int
    active: int
    active_local: int
    active_remote: int
    active_reachable: int
    probed: int
    delivery_mode: str
    cdn_base_url: str

    def line(self) -> str:
        cdn = self.cdn_base_url or "unset"
        probe = f"{self.active_remote}/{self.probed}" if self.probed else "not probed"
        return (
            f"receipt_coverage registered={self.registered} "
            f"registered_local={self.registered_local}/{self.registered} "
            f"active={self.active} active_local={self.active_local}/{self.active} "
            f"active_cdn={probe} "
            f"active_reachable={self.active_reachable}/{self.active} "
            f"mode={self.delivery_mode} cdn={cdn}"
        )


def _has_local_bytes(registry: CorpusRegistry, document) -> bool:
    """Size-only check.

    The real delivery path hashes the file and reopens the PDF; doing that for
    every document at boot would cost minutes. A present file of the right size
    is enough to tell "bytes were shipped" from "bytes are missing", which is
    the question this log answers.
    """
    try:
        path = registry.local_path(document)
    except Exception:
        return False
    try:
        return path.is_file() and path.stat().st_size == document.byte_size
    except OSError:
        return False


def receipt_coverage(
    registry: CorpusRegistry,
    *,
    delivery_mode: str,
    cdn_base_url: str = "",
    probe_remote: bool = True,
) -> ReceiptCoverage:
    local_ids = {
        document.document_id
        for document in registry.documents.values()
        if _has_local_bytes(registry, document)
    }
    active = [
        registry.documents[item.document_id]
        for item in registry.active_documents.values()
        if item.document_id in registry.documents
    ]
    active_local = {
        document.document_id for document in active if document.document_id in local_ids
    }

    remote_ids: set[str] = set()
    probed = 0
    if cdn_base_url and probe_remote:
        storage = CdnCorpusStorage(cdn_base_url, timeout=PROBE_TIMEOUT_SECONDS)
        deadline = time.monotonic() + PROBE_BUDGET_SECONDS
        for document in active:
            if time.monotonic() >= deadline:
                break
            probed += 1
            try:
                storage.verify(document)
            except Exception:
                continue
            remote_ids.add(document.document_id)

    return ReceiptCoverage(
        registered=len(registry.documents),
        registered_local=len(local_ids),
        active=len(active),
        active_local=len(active_local),
        active_remote=len(remote_ids),
        active_reachable=len(active_local | remote_ids),
        probed=probed,
        delivery_mode=delivery_mode,
        cdn_base_url=cdn_base_url,
    )


def log_receipt_coverage(
    registry: CorpusRegistry, *, delivery_mode: str, cdn_base_url: str = ""
) -> ReceiptCoverage | None:
    """Never let a coverage report stop the app from booting."""
    try:
        coverage = receipt_coverage(
            registry, delivery_mode=delivery_mode, cdn_base_url=cdn_base_url
        )
    except Exception:
        logger.exception("receipt_coverage unavailable")
        return None
    logger.info("%s", coverage.line())
    return coverage
