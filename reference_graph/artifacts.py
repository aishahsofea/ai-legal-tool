"""Deterministic candidate and promoted artifact storage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import GRAPH_SCHEMA_VERSION, Candidate, Edge, Provision, SourceDocument, UnresolvedReference

ARTIFACT_NAMES = ("provisions.json", "edges.json", "unresolved.json", "audit.json")


def graph_dir(root: Path, document_id: str) -> Path:
    return root / document_id


def candidate_dir(root: Path, document_id: str) -> Path:
    return graph_dir(root, document_id) / ".work"


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"artifact_unreadable:{path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"artifact_not_object:{path.name}")
    return value


def write_candidate(root: Path, document: SourceDocument, provisions: list[Provision], edges: list[Edge],
                    unresolved: list[UnresolvedReference], candidates: list[Candidate]) -> Path:
    """Write a review candidate, never an API-visible promoted index."""
    target = candidate_dir(root, document.document_id)
    base = {"schema_version": GRAPH_SCHEMA_VERSION, "state": "candidate", "document": document.__dict__}
    _dump(target / "provisions.json", {**base, "provisions": [item.to_dict() for item in provisions]})
    _dump(target / "edges.json", {**base, "edges": [item.to_dict() for item in edges]})
    _dump(target / "unresolved.json", {**base, "unresolved": [item.to_dict() for item in unresolved]})
    _dump(target / "audit.json", {
        **base,
        "audit_state": "pending_human_edge_audit",
        "instructions": "Inspect every proposed edge against its immutable PDF receipt before assigning approved or rejected.",
        "decision_submission": {
            "format": "{\"decisions\": {\"candidate:<id>\": {\"decision\": \"approved|rejected\", \"audit_note\": \"...\"}}}",
            "requirement": "A decision and audit note are required for every candidate_id.",
        },
        "candidates": [{**item.to_dict(), "decision": "pending", "audit_note": ""} for item in candidates],
    })
    return target


def load_artifacts(directory: Path) -> dict[str, dict[str, Any]]:
    values = {name.removesuffix(".json"): _load(directory / name) for name in ARTIFACT_NAMES}
    document_ids = {str(value.get("document", {}).get("document_id", "")) for value in values.values()}
    if len(document_ids) != 1 or not next(iter(document_ids)):
        raise ValueError("artifact_document_identity_mismatch")
    return values


def write_promoted(root: Path, document_id: str, artifacts: dict[str, dict[str, Any]]) -> Path:
    target = graph_dir(root, document_id)
    for name, payload in artifacts.items():
        value = {**payload, "state": "promoted"}
        _dump(target / f"{name}.json", value)
    return target


def read_decisions(path: Path) -> dict[str, dict[str, str]]:
    value = _load(path)
    items = value.get("decisions", value)
    if not isinstance(items, dict):
        raise ValueError("audit_decisions_malformed")
    result: dict[str, dict[str, str]] = {}
    for candidate_id, item in items.items():
        if isinstance(item, str):
            item = {"decision": item, "audit_note": ""}
        if not isinstance(item, dict) or item.get("decision") not in {"approved", "rejected"}:
            raise ValueError("audit_decision_invalid")
        result[str(candidate_id)] = {"decision": str(item["decision"]), "audit_note": str(item.get("audit_note", ""))}
    return result


def apply_audit_decisions(root: Path, document_id: str, decisions: dict[str, dict[str, str]]) -> Path:
    target = candidate_dir(root, document_id)
    audit = _load(target / "audit.json")
    candidates = audit.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("audit_candidates_malformed")
    expected = {str(item.get("candidate_id", "")) for item in candidates}
    if expected != set(decisions):
        raise ValueError("audit_decisions_not_complete")
    audit["candidates"] = [
        {**item, **decisions[str(item["candidate_id"])]}
        for item in candidates
    ]
    audit["audit_state"] = "human_edge_audit_complete"
    _dump(target / "audit.json", audit)
    return target


def promote(root: Path, document_id: str) -> Path:
    """Promote only a complete human decision set; rejected references become unresolved."""
    candidate = load_artifacts(candidate_dir(root, document_id))
    audits = candidate["audit"].get("candidates", [])
    if not isinstance(audits, list) or any(item.get("decision") not in {"approved", "rejected"} for item in audits):
        raise ValueError("human_edge_audit_required")
    decisions = {str(item["candidate_id"]): str(item["decision"]) for item in audits}
    approved = {candidate_id for candidate_id, decision in decisions.items() if decision == "approved"}
    rejected = {candidate_id for candidate_id, decision in decisions.items() if decision == "rejected"}
    edge_candidates = {str(item["candidate_id"]): item for item in audits}
    edges = []
    for edge in candidate["edges"].get("edges", []):
        edge_candidate = next((item for item in audits if item.get("source_provision_id") == edge.get("source_provision_id")
                               and item.get("literal") == edge.get("evidence", {}).get("text")
                               and item.get("evidence", {}).get("start_offset") == edge.get("evidence", {}).get("start_offset")), None)
        if edge_candidate and edge_candidate.get("candidate_id") in approved:
            edges.append(edge)
    # A rejected unresolved candidate replaces its parser reason with the human
    # audit outcome; it must not create a duplicate unresolved record.
    unresolved = [item for item in candidate["unresolved"].get("unresolved", [])
                  if str(item.get("candidate_id")) not in rejected]
    for candidate_id in sorted(rejected):
        item = edge_candidates[candidate_id]
        unresolved.append({
            "candidate_id": candidate_id, "source_provision_id": item["source_provision_id"],
            "source_version_id": item["source_version_id"], "literal": item["literal"],
            "reference_kind": item["reference_kind"], "reason_code": "audit_rejected", "evidence": item["evidence"],
        })
    promoted = {
        "provisions": candidate["provisions"],
        "edges": {**candidate["edges"], "edges": edges},
        "unresolved": {**candidate["unresolved"], "unresolved": unresolved},
        "audit": {**candidate["audit"], "audit_state": "promoted_after_human_edge_audit"},
    }
    return write_promoted(root, document_id, promoted)
