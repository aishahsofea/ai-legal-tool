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


def decision_template(root: Path, document_id: str) -> dict[str, Any]:
    """Export a complete, receipt-bound form without inferring any decision."""
    report = audit_report(root, document_id)
    decisions = {}
    for item in report["candidates"]:
        decisions[str(item["candidate_id"])] = {
            "decision": "",
            "audit_note": "",
            "review_context": {
                "source_provision_id": item.get("source_provision_id"),
                "literal": item.get("literal"),
                "resolution": item.get("resolution"),
                "reason_code": item.get("reason_code"),
                "target_provision_ids": item.get("target_provision_ids", []),
                "evidence": item.get("evidence"),
            },
        }
    return {
        "document_id": document_id,
        "receipt_path": report["receipt_path"],
        "instructions": (
            "Inspect the exact receipt evidence for every entry. For a resolved entry, "
            "inspect every listed target and approve only if all listed edges are literal "
            "and correct. For an unresolved entry, approve only if the unresolved outcome "
            "is accurate. Set approved or rejected and write a non-empty audit_note."
        ),
        "decisions": decisions,
    }
