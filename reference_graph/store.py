"""Read-only promoted graph index used by the API; it never parses PDFs."""
from __future__ import annotations

import json
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from typing import Any

from corpus.registry import DEFAULT_MANIFEST_PATH, CorpusRegistry

from .artifacts import graph_dir, load_artifacts
from .comparison import compare_neighborhoods
from .validation import validate_artifacts


class GraphNotIndexed(FileNotFoundError):
    pass


class GraphUnavailable(RuntimeError):
    pass


class GraphPairMismatch(ValueError):
    pass


class ReferenceGraphStore:
    """Authoritative artifact read path for the API.

    PostgreSQL loading is an optional deployment mirror/verification target; API
    responses always come from the same validated promoted artifact representation.
    """

    def __init__(self, root: Path, *, manifest_path: Path = DEFAULT_MANIFEST_PATH):
        self.root = Path(root)
        self.manifest_path = Path(manifest_path)

    @lru_cache(maxsize=64)
    def _artifact_id(self, document_id: str) -> str:
        direct = graph_dir(self.root, document_id)
        if direct.is_dir() and (direct / "provisions.json").is_file():
            return document_id
        if self.root.is_dir():
            for directory in sorted(self.root.iterdir(), key=lambda path: path.name):
                path = directory / "provisions.json"
                if not path.is_file():
                    continue
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                document = payload.get("document", {}) if isinstance(payload, dict) else {}
                if document.get("corpus_document_id") == document_id:
                    return directory.name
        raise GraphNotIndexed(document_id)

    @lru_cache(maxsize=32)
    def _load(self, document_id: str) -> dict[str, dict[str, Any]]:
        directory = graph_dir(self.root, self._artifact_id(document_id))
        if not directory.exists() or not all((directory / name).exists() for name in ("provisions.json", "edges.json", "unresolved.json", "audit.json")):
            raise GraphNotIndexed(document_id)
        result = validate_artifacts(directory, require_promoted=True)
        if not result["valid"]:
            raise GraphUnavailable(result["errors"])
        return load_artifacts(directory)

    def status(self, document_id: str) -> dict[str, Any]:
        data = self._load(document_id)
        directory = graph_dir(self.root, self._artifact_id(document_id))
        return {"status": "available", "document_id": document_id, "counts": validate_artifacts(directory)["counts"],
                "document": data["provisions"]["document"]}

    def document(self, document_id: str) -> dict[str, Any]:
        return dict(self._load(document_id)["provisions"]["document"])

    def neighborhood(self, document_id: str, focus_provision_id: str) -> dict[str, Any]:
        data = self._load(document_id)
        provisions = {item["provision_id"]: item for item in data["provisions"]["provisions"]}
        focus = provisions.get(focus_provision_id)
        if focus is None:
            return {"status": "provision_not_found", "document_id": document_id, "focus_provision_id": focus_provision_id}
        edges = [edge for edge in data["edges"]["edges"] if edge["source_provision_id"] == focus_provision_id or edge["target_provision_id"] == focus_provision_id]
        related = {focus_provision_id}
        for edge in edges:
            related.add(edge["source_provision_id"])
            related.add(edge["target_provision_id"])
        # Cross-act targets are version-neutral and intentionally can lack a local node.
        nodes = [provisions[provision_id] for provision_id in sorted(related) if provision_id in provisions]
        return {"status": "available", "document_id": document_id, "focus_provision_id": focus_provision_id,
                "nodes": nodes, "edges": edges}

    def compare(
        self,
        base_document_id: str,
        compare_document_id: str,
        focus_provision_id: str,
    ) -> dict[str, Any]:
        base_document = self.document(base_document_id)
        compare_document = self.document(compare_document_id)
        if (
            base_document.get("act_number") != compare_document.get("act_number")
            or base_document.get("language") != compare_document.get("language")
        ):
            raise GraphPairMismatch("snapshot_pair_act_or_language_mismatch")
        base = self.neighborhood(base_document_id, focus_provision_id)
        compare = self.neighborhood(compare_document_id, focus_provision_id)
        focus_presence = {
            "base": base.get("status") == "available",
            "compare": compare.get("status") == "available",
        }
        if not focus_presence["base"] or not focus_presence["compare"]:
            return {
                "status": "focus_missing_base" if not focus_presence["base"] else "focus_missing_compare",
                "base_document_id": base_document_id,
                "compare_document_id": compare_document_id,
                "focus_provision_id": focus_provision_id,
                "focus_presence": focus_presence,
                "missing_focus_documents": [
                    label for label, present in focus_presence.items() if not present
                ],
            }
        return compare_neighborhoods(
            base,
            compare,
            base_document_id=base_document_id,
            compare_document_id=compare_document_id,
            focus_provision_id=focus_provision_id,
        )

    def available_snapshots(
        self,
        *,
        act_number: str,
        language: str,
    ) -> list[dict[str, Any]]:
        try:
            registry = CorpusRegistry(self.manifest_path)
        except Exception as exc:
            raise GraphUnavailable("snapshot_manifest_unavailable") from exc
        snapshots = []
        if not self.root.is_dir():
            return snapshots
        for directory in sorted(self.root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                artifact_document = self.document(directory.name)
            except (GraphNotIndexed, GraphUnavailable, ValueError):
                continue
            if (
                str(artifact_document.get("act_number", "")) != str(act_number)
                or str(artifact_document.get("language", "")) != language
            ):
                continue
            try:
                corpus_document = registry.get(str(artifact_document["corpus_document_id"]))
            except Exception as exc:
                raise GraphUnavailable("snapshot_corpus_identity_unavailable") from exc
            snapshots.append({
                "document_id": directory.name,
                "corpus_document_id": corpus_document.document_id,
                "act_number": corpus_document.act_number,
                "act_title": corpus_document.act_title,
                "language": corpus_document.language,
                "snapshot_date": corpus_document.timeline_date,
                "snapshot_type": corpus_document.timeline_type,
                "source_url": corpus_document.source_url,
                "sha256": corpus_document.sha256,
                "byte_size": corpus_document.byte_size,
                "page_count": corpus_document.page_count,
                "receipt_path": artifact_document.get("receipt_path", f"/receipts/{directory.name}/pdf"),
            })

        def order(item: dict[str, Any]) -> tuple[datetime, str]:
            try:
                parsed = datetime.strptime(str(item["snapshot_date"]), "%d/%m/%Y")
            except ValueError:
                parsed = datetime.max
            return parsed, str(item["document_id"])

        return sorted(snapshots, key=order)
