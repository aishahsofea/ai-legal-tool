"""Read-only promoted graph index used by the API; it never parses PDFs."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .artifacts import graph_dir, load_artifacts
from .validation import validate_artifacts


class GraphNotIndexed(FileNotFoundError):
    pass


class GraphUnavailable(RuntimeError):
    pass


class ReferenceGraphStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    @lru_cache(maxsize=32)
    def _load(self, document_id: str) -> dict[str, dict[str, Any]]:
        directory = graph_dir(self.root, document_id)
        if not directory.exists() or not all((directory / name).exists() for name in ("provisions.json", "edges.json", "unresolved.json", "audit.json")):
            raise GraphNotIndexed(document_id)
        result = validate_artifacts(directory, require_promoted=True)
        if not result["valid"]:
            raise GraphUnavailable(result["errors"])
        return load_artifacts(directory)

    def status(self, document_id: str) -> dict[str, Any]:
        data = self._load(document_id)
        return {"status": "available", "document_id": document_id, "counts": validate_artifacts(graph_dir(self.root, document_id))["counts"],
                "document": data["provisions"]["document"]}

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
