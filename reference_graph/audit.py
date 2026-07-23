"""Human-audit report helpers. Decisions are intentionally never inferred."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import candidate_dir, load_artifacts


def audit_report(root: Path, document_id: str) -> dict[str, Any]:
    artifacts = load_artifacts(candidate_dir(root, document_id))
    audit = artifacts["audit"]
    candidates = audit.get("candidates", [])
    pending = [item for item in candidates if item.get("decision") == "pending"]
    return {
        "document_id": document_id,
        "audit_state": audit.get("audit_state"),
        "candidate_count": len(candidates),
        "pending_count": len(pending),
        "receipt_path": artifacts["provisions"].get("document", {}).get("receipt_path", ""),
        "manual_gate_required": bool(pending),
        "candidates": candidates,
    }
