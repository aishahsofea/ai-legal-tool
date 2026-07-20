"""Manifest-backed historical lookup and fail-closed local integrity checks."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

import fitz

from corpus.identity import asset_key, document_id, extraction_id, sha256_file
from corpus.models import ActiveDocument, CorpusDocument, ExtractionRun
from corpus.sidecars import read_sidecar

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = REPOSITORY_ROOT / "data" / "pdfs" / "manifest.json"
DEFAULT_ASSET_ROOT = REPOSITORY_ROOT / "data" / "pdfs"
DEFAULT_SIDECAR_ROOT = REPOSITORY_ROOT / "data" / "corpus" / "sidecars"


class CorpusManifestError(RuntimeError):
    """The corpus manifest is absent, unsafe, or internally inconsistent."""


class CorpusDocumentNotFound(KeyError):
    """No immutable document has the requested identity."""


class CorpusDocumentIntegrityError(RuntimeError):
    """Registered bytes or coordinates do not match their immutable identity."""


class CorpusRegistry:
    def __init__(
        self,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        *,
        asset_root: Path | None = None,
        sidecar_root: Path | None = None,
    ):
        self.manifest_path = Path(manifest_path).resolve()
        self.asset_root = Path(
            asset_root or os.getenv("CORPUS_LOCAL_ROOT") or self.manifest_path.parent
        ).resolve()
        self.sidecar_root = Path(
            sidecar_root or os.getenv("CORPUS_SIDECAR_ROOT") or DEFAULT_SIDECAR_ROOT
        ).resolve()
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorpusManifestError("Corpus manifest could not be loaded") from exc

        version = raw.get("schema_version")
        if version not in {1, 2} or not isinstance(raw.get("documents"), list):
            raise CorpusManifestError("Unsupported or malformed corpus manifest")
        self.schema_version = int(version)

        try:
            documents = self._parse_documents(raw["documents"], version)
            extractions = self._parse_extractions(raw.get("extraction_runs", []), documents)
            active = self._parse_active(raw.get("active_documents", []), documents, extractions)
            aliases = self._parse_aliases(raw.get("aliases", {}), documents)
            observations = self._parse_source_observations(
                raw.get("source_observations", []), documents
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorpusManifestError("Corpus manifest contains invalid metadata") from exc

        self.documents = documents
        self.extraction_runs = extractions
        self.active_documents = active
        self.aliases = aliases
        self.source_observations = observations
        self.extractions_by_document: dict[str, list[ExtractionRun]] = {}
        self.documents_by_act_language: dict[tuple[str, str], list[CorpusDocument]] = {}
        for extraction in extractions.values():
            self.extractions_by_document.setdefault(extraction.document_id, []).append(extraction)
        for runs in self.extractions_by_document.values():
            runs.sort(key=lambda run: run.extraction_id)
        for document in documents.values():
            self.documents_by_act_language.setdefault(
                (document.act_number, document.language), []
            ).append(document)
        for versions in self.documents_by_act_language.values():
            versions.sort(key=lambda item: item.document_id)

        # Compatibility view only. New receipt enrichment must use get(document_id).
        self.documents_by_act: dict[str, CorpusDocument] = {}
        for (act_number, language), mapping in active.items():
            if language == "en" or act_number not in self.documents_by_act:
                self.documents_by_act[act_number] = documents[mapping.document_id]
        if version == 1:
            self.documents_by_act = {document.act_number: document for document in documents.values()}

    def _parse_documents(self, raw_documents: list[dict], version: int) -> dict[str, CorpusDocument]:
        documents: dict[str, CorpusDocument] = {}
        for raw in raw_documents:
            if version == 1:
                digest = str(raw["sha256"])
                raw = {
                    **raw,
                    "asset_key": asset_key(digest),
                    "local_path": raw.get("asset_path", ""),
                    "lifecycle_status": "active",
                    "document_kind": "reprint",
                }
            document = CorpusDocument.from_dict(raw)
            if document.document_id in documents:
                raise ValueError("duplicate document identity")
            expected = document_id(document.act_number, document.language, document.sha256)
            if version == 2 and document.document_id != expected:
                raise ValueError("document identity does not match its bytes")
            self._safe_local_path(document.local_path, self.asset_root)
            documents[document.document_id] = document
        return documents

    def _parse_extractions(
        self,
        values: list[dict], documents: dict[str, CorpusDocument]
    ) -> dict[str, ExtractionRun]:
        result: dict[str, ExtractionRun] = {}
        for value in values:
            extraction = ExtractionRun.from_dict(value)
            expected_identity = extraction_id(
                extraction.document_id,
                extraction.extractor,
                extraction.extractor_version,
                extraction.configuration_hash,
            )
            if (
                extraction.extraction_id in result
                or extraction.document_id not in documents
                or extraction.extraction_id != expected_identity
            ):
                raise ValueError("duplicate or orphan extraction")
            sidecar = extraction.coordinate_sidecar
            if sidecar is not None:
                expected_key = (
                    f"statutes/extractions/{extraction.extraction_id}/"
                    f"{sidecar.sha256}.words.json.gz"
                )
                if sidecar.asset_key != expected_key:
                    raise ValueError("coordinate sidecar identity mismatch")
                self._safe_local_path(sidecar.local_path, self.sidecar_root)
            result[extraction.extraction_id] = extraction
        return result

    @staticmethod
    def _parse_active(
        values: list[dict],
        documents: dict[str, CorpusDocument],
        extractions: dict[str, ExtractionRun],
    ) -> dict[tuple[str, str], ActiveDocument]:
        result: dict[tuple[str, str], ActiveDocument] = {}
        for value in values:
            mapping = ActiveDocument.from_dict(value)
            key = (mapping.act_number, mapping.language)
            document = documents.get(mapping.document_id)
            extraction = extractions.get(mapping.extraction_id)
            previous = documents.get(mapping.previous_document_id) if mapping.previous_document_id else None
            if (
                key in result
                or document is None
                or extraction is None
                or extraction.status != "ready"
                or extraction.document_id != document.document_id
                or (document.act_number, document.language) != key
                or (previous is not None and (previous.act_number, previous.language) != key)
                or (mapping.previous_document_id and previous is None)
            ):
                raise ValueError("invalid active document mapping")
            result[key] = mapping
        return result

    @staticmethod
    def _parse_aliases(values: object, documents: dict[str, CorpusDocument]) -> dict[str, str]:
        if not isinstance(values, dict):
            raise ValueError("aliases must be an object")
        aliases = {str(alias): str(target) for alias, target in values.items()}
        if any(alias in documents or target not in documents for alias, target in aliases.items()):
            raise ValueError("invalid historical document alias")
        return aliases

    @staticmethod
    def _parse_source_observations(
        values: object, documents: dict[str, CorpusDocument]
    ) -> list[dict[str, str]]:
        if not isinstance(values, list):
            raise ValueError("source observations must be a list")
        observations: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("invalid source observation")
            observation = {
                "document_id": str(value.get("document_id", "")),
                "source_url": str(value.get("source_url", "")),
                "observed_at": str(value.get("observed_at", "")),
            }
            key = (
                observation["document_id"], observation["source_url"],
                observation["observed_at"],
            )
            if (
                observation["document_id"] not in documents
                or not observation["source_url"].startswith("https://")
                or not observation["observed_at"]
                or key in seen
            ):
                raise ValueError("invalid source observation")
            seen.add(key)
            observations.append(observation)
        return sorted(
            observations,
            key=lambda item: (item["document_id"], item["source_url"], item["observed_at"]),
        )

    @staticmethod
    def _safe_local_path(value: str, root: Path) -> Path | None:
        if not value:
            return None
        relative = Path(value)
        if relative.is_absolute():
            raise ValueError("corpus local path must be relative")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("corpus local path escapes its root") from exc
        return resolved

    def get(self, identity: str) -> CorpusDocument:
        resolved = self.aliases.get(identity, identity)
        try:
            return self.documents[resolved]
        except KeyError as exc:
            raise CorpusDocumentNotFound(identity) from exc

    def versions_for_act(self, act_number: object, language: str | None = None) -> list[CorpusDocument]:
        act = str(act_number or "")
        if language:
            return list(self.documents_by_act_language.get((act, language), []))
        return sorted(
            (
                document
                for (number, _language), versions in self.documents_by_act_language.items()
                if number == act
                for document in versions
            ),
            key=lambda document: (document.language, document.document_id),
        )

    def for_act(self, act_number: object, language: str | None = None) -> CorpusDocument | None:
        """Compatibility/current lookup; never use this to infer chunk provenance."""
        act = str(act_number or "")
        if language is not None:
            mapping = self.active_documents.get((act, language))
            return self.documents.get(mapping.document_id) if mapping else None
        return self.documents_by_act.get(act)

    def extraction(self, extraction_identity: str) -> ExtractionRun:
        try:
            return self.extraction_runs[extraction_identity]
        except KeyError as exc:
            raise CorpusDocumentNotFound(extraction_identity) from exc

    def active_extraction(self, document: CorpusDocument) -> ExtractionRun | None:
        mapping = self.active_documents.get((document.act_number, document.language))
        if not mapping or mapping.document_id != document.document_id:
            return None
        return self.extraction_runs[mapping.extraction_id]

    def local_path(self, document: CorpusDocument) -> Path:
        path = self._safe_local_path(document.local_path, self.asset_root)
        if path is None:
            raise CorpusDocumentIntegrityError("Corpus document has no local asset")
        return path

    def validate(self, document: CorpusDocument, *, deep: bool = True) -> Path:
        try:
            path = self.local_path(document)
            if not path.is_file() or path.stat().st_size != document.byte_size:
                raise CorpusDocumentIntegrityError("Corpus document size mismatch")
            if deep and sha256_file(path) != document.sha256:
                raise CorpusDocumentIntegrityError("Corpus document hash mismatch")
            with fitz.open(path) as pdf:
                if pdf.page_count != document.page_count:
                    raise CorpusDocumentIntegrityError("Corpus document page-count mismatch")
        except CorpusDocumentIntegrityError:
            logger.error("corpus_integrity_failure document_id=%s", document.document_id)
            raise
        except Exception as exc:
            logger.error("corpus_integrity_failure document_id=%s", document.document_id)
            raise CorpusDocumentIntegrityError("Corpus document is unavailable") from exc
        return path

    def validate_exact_extraction(
        self, document: CorpusDocument, extraction_identity: str | None
    ) -> ExtractionRun:
        if not extraction_identity:
            raise CorpusDocumentIntegrityError("Receipt extraction identity is missing")
        extraction = self.extraction_runs.get(extraction_identity)
        if (
            extraction is None
            or extraction.document_id != document.document_id
            or extraction.status != "ready"
        ):
            raise CorpusDocumentIntegrityError("Receipt extraction identity is not ready")
        return extraction

    def sidecar_path(self, extraction: ExtractionRun) -> Path:
        sidecar = extraction.coordinate_sidecar
        if sidecar is None or not sidecar.local_path:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar is unavailable")
        try:
            path = self._safe_local_path(sidecar.local_path, self.sidecar_root)
        except ValueError as exc:
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar path is unsafe") from exc
        assert path is not None
        if (
            not path.is_file()
            or path.stat().st_size != sidecar.byte_size
            or sha256_file(path) != sidecar.sha256
        ):
            raise CorpusDocumentIntegrityError("Receipt coordinate sidecar integrity check failed")
        return path

    def validate_sidecar(self, extraction: ExtractionRun, *, deep: bool = True) -> Path:
        path = self.sidecar_path(extraction)
        if deep:
            try:
                document = self.get(extraction.document_id)
                read_sidecar(path, document.document_id, document.sha256)
            except (CorpusDocumentNotFound, ValueError) as exc:
                raise CorpusDocumentIntegrityError(
                    "Receipt coordinate sidecar identity check failed"
                ) from exc
        return path

    def validated_for_act(self, act_number: object, language: str | None = None) -> CorpusDocument | None:
        document = self.for_act(act_number, language)
        if document is None:
            return None
        try:
            self.validate(document)
        except CorpusDocumentIntegrityError:
            return None
        return document


@lru_cache(maxsize=1)
def get_corpus_registry() -> CorpusRegistry:
    path = Path(os.getenv("CORPUS_MANIFEST_PATH", str(DEFAULT_MANIFEST_PATH)))
    return CorpusRegistry(path)
