"""Local and HTTP-CDN delivery adapters for immutable corpus objects."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from urllib.parse import quote

import requests

from corpus.models import CorpusDocument, ExtractionRun
from corpus.registry import CorpusDocumentIntegrityError, CorpusRegistry


@dataclass(frozen=True)
class ObjectMetadata:
    byte_size: int
    sha256: str
    etag: str
    content_type: str


class CdnCorpusStorage:
    def __init__(self, base_url: str, *, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def object_url(self, asset_key: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in asset_key.split("/"))
        return f"{self.base_url}/{encoded}"

    def url(self, document: CorpusDocument) -> str:
        return self.object_url(document.asset_key)

    def _verify_object(
        self,
        asset_key: str,
        byte_size: int,
        sha256: str,
        content_types: set[str],
    ) -> ObjectMetadata:
        try:
            response = requests.head(
                self.object_url(asset_key), timeout=self.timeout, allow_redirects=True
            )
            response.raise_for_status()
            size = int(response.headers.get("Content-Length", "-1"))
            digest = (
                response.headers.get("X-Corpus-SHA256")
                or response.headers.get("X-Amz-Meta-Sha256")
                or ""
            ).lower()
            etag = response.headers.get("ETag", "").strip()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        except Exception as exc:
            raise CorpusDocumentIntegrityError("Corpus CDN object is unavailable") from exc
        if size != byte_size or digest != sha256 or content_type not in content_types:
            raise CorpusDocumentIntegrityError("Corpus CDN object metadata mismatch")
        return ObjectMetadata(size, digest, etag, content_type)

    def verify(self, document: CorpusDocument) -> ObjectMetadata:
        return self._verify_object(
            document.asset_key,
            document.byte_size,
            document.sha256,
            {"application/pdf"},
        )

    def deep_verify(self, document: CorpusDocument) -> None:
        """Stream and hash the full immutable object for an operator deep audit."""
        response = None
        try:
            response = requests.get(
                self.url(document), timeout=self.timeout, stream=True
            )
            response.raise_for_status()
            digest = hashlib.sha256()
            byte_size = 0
            for block in response.iter_content(1024 * 1024):
                if block:
                    byte_size += len(block)
                    digest.update(block)
        except Exception as exc:
            raise CorpusDocumentIntegrityError("Corpus CDN deep verification failed") from exc
        finally:
            if response is not None:
                response.close()
        if byte_size != document.byte_size or digest.hexdigest() != document.sha256:
            raise CorpusDocumentIntegrityError("Corpus CDN object byte integrity mismatch")

    def verify_sidecar(self, run: ExtractionRun) -> ObjectMetadata:
        sidecar = run.coordinate_sidecar
        if sidecar is None:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar is unavailable")
        return self._verify_object(
            sidecar.asset_key,
            sidecar.byte_size,
            sidecar.sha256,
            {"application/gzip", "application/octet-stream"},
        )

    def get_sidecar(self, run: ExtractionRun) -> bytes:
        sidecar = run.coordinate_sidecar
        if sidecar is None:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar is unavailable")
        try:
            response = requests.get(
                self.object_url(sidecar.asset_key), timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.content
        except Exception as exc:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar download failed") from exc
        if len(payload) != sidecar.byte_size or hashlib.sha256(payload).hexdigest() != sidecar.sha256:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar integrity check failed")
        return payload

    def get(self, document: CorpusDocument, range_header: str | None = None) -> requests.Response:
        headers = {"Range": range_header} if range_header else {}
        response = requests.get(
            self.url(document), headers=headers, timeout=self.timeout, stream=True
        )
        if response.status_code not in {200, 206}:
            response.close()
            raise CorpusDocumentIntegrityError("Corpus CDN delivery failed")
        return response


def configured_cdn_storage() -> CdnCorpusStorage | None:
    base_url = os.getenv("CORPUS_CDN_BASE_URL", "").strip()
    return CdnCorpusStorage(base_url) if base_url else None


def verify_local(registry: CorpusRegistry, document: CorpusDocument):
    return registry.validate(document)
