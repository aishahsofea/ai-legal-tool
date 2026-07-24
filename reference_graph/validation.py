"""Pure validation for graph candidates and promoted indexes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import load_artifacts
from .models import GRAPH_SCHEMA_VERSION, PROVISION_KINDS

_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "reference_graph"


def _schema_contract_errors(name: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    """Validate the stable, used subset of the checked-in JSON Schema contract.

    The pipeline deliberately has no runtime schema-library dependency: builds
    must work offline from a clean operator environment.  These checks cover the
    required fields plus the const/enum constraints used by the four schemas.
    """
    try:
        schema = json.loads((_SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [{"code": "schema_unreadable", "artifact": name, "detail": type(exc).__name__}]
    errors: list[dict[str, str]] = []
    for field in schema.get("required", []):
        if field not in payload:
            errors.append({"code": "schema_required_missing", "artifact": name, "field": str(field)})
    for field, rule in schema.get("properties", {}).items():
        if field not in payload or not isinstance(rule, dict):
            continue
        value = payload[field]
        if "const" in rule and value != rule["const"]:
            errors.append({"code": "schema_const_mismatch", "artifact": name, "field": field})
        if "enum" in rule and value not in rule["enum"]:
            errors.append({"code": "schema_enum_mismatch", "artifact": name, "field": field})
        if rule.get("type") == "array" and isinstance(value, list):
            item_rule = rule.get("items", {})
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    errors.append({"code": "schema_item_not_object", "artifact": name, "field": field})
                    continue
                for required in item_rule.get("required", []):
                    if required not in item:
                        errors.append({"code": "schema_item_required_missing", "artifact": name,
                                       "field": f"{field}[{index}].{required}"})
    return errors


def _has_receipt_provenance(item: dict[str, Any]) -> bool:
    evidence = item.get("evidence")
    if not isinstance(evidence, dict):
        return False
    pages = evidence.get("pages")
    return isinstance(pages, list) and bool(pages) and all(
        isinstance(page, dict) and isinstance(page.get("rectangles"), list) and bool(page["rectangles"])
        for page in pages
    )


def validate_artifacts(directory: Path, *, require_promoted: bool = False) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    try:
        artifacts = load_artifacts(directory)
    except ValueError as exc:
        return {"valid": False, "errors": [{"code": str(exc)}], "counts": {}}
    states = {payload.get("state") for payload in artifacts.values()}
    document = artifacts["provisions"].get("document", {})
    document_id = str(document.get("document_id", ""))
    act_number = str(document.get("act_number", ""))
    if len(states) != 1 or states == {None}:
        errors.append({"code": "artifact_state_mismatch"})
    if require_promoted and states != {"promoted"}:
        errors.append({"code": "artifact_not_promoted"})
    if any(payload.get("schema_version") != GRAPH_SCHEMA_VERSION for payload in artifacts.values()):
        errors.append({"code": "schema_version_mismatch"})
    for name, payload in artifacts.items():
        errors.extend(_schema_contract_errors(name, payload))
    provisions = artifacts["provisions"].get("provisions", [])
    edges = artifacts["edges"].get("edges", [])
    unresolved = artifacts["unresolved"].get("unresolved", [])
    audit = artifacts["audit"].get("candidates", [])
    if not all(isinstance(value, list) for value in (provisions, edges, unresolved, audit)):
        errors.append({"code": "artifact_array_malformed"})
        return {"valid": False, "errors": errors, "counts": {}}
    ids = [str(item.get("provision_id", "")) for item in provisions]
    if not ids or len(ids) != len(set(ids)):
        errors.append({"code": "duplicate_or_missing_provision_id"})
    known = set(ids)
    for provision in provisions:
        if provision.get("kind") not in PROVISION_KINDS:
            errors.append({"code": "invalid_provision_kind", "provision_id": str(provision.get("provision_id", ""))})
        if str(provision.get("version_id", "")) != f"{document_id}/provision:{provision.get('provision_id', '')}":
            errors.append({"code": "provision_version_id_mismatch", "provision_id": str(provision.get("provision_id", ""))})
        if int(provision.get("start_offset", -1)) < 0 or int(provision.get("end_offset", -1)) < int(provision.get("start_offset", -1)):
            errors.append({"code": "invalid_half_open_offsets", "provision_id": str(provision.get("provision_id", ""))})
    seen_edges: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id", ""))
        if not edge_id or edge_id in seen_edges:
            errors.append({"code": "duplicate_or_missing_edge_id"})
        seen_edges.add(edge_id)
        if edge.get("source_provision_id") not in known:
            errors.append({"code": "edge_source_not_indexed", "edge_id": edge_id})
        if edge.get("source_version_id") != f"{document_id}/provision:{edge.get('source_provision_id', '')}":
            errors.append({"code": "edge_source_version_id_mismatch", "edge_id": edge_id})
        target = str(edge.get("target_provision_id", ""))
        local_target = target == f"act:{act_number}" or target.startswith(f"act:{act_number}/")
        expected_target_version = f"{document_id}/provision:{target}" if target in known else None
        if edge.get("target_version_id") != expected_target_version:
            errors.append({
                "code": "edge_target_version_id_mismatch",
                "edge_id": edge_id,
            })
        if not local_target and edge.get("target_version_id") is not None:
            errors.append({"code": "cross_act_target_must_be_version_neutral", "edge_id": edge_id})
        evidence = edge.get("evidence", {})
        if not isinstance(evidence, dict) or int(evidence.get("end_offset", -1)) < int(evidence.get("start_offset", -1)):
            errors.append({"code": "edge_evidence_offsets_invalid", "edge_id": edge_id})
        if not _has_receipt_provenance(edge):
            errors.append({"code": "edge_evidence_provenance_missing", "edge_id": edge_id})
    for item in [*unresolved, *audit]:
        if not _has_receipt_provenance(item):
            errors.append({"code": "evidence_provenance_missing", "candidate_id": str(item.get("candidate_id", ""))})
        if item.get("source_version_id") != f"{document_id}/provision:{item.get('source_provision_id', '')}":
            errors.append({
                "code": "candidate_source_version_id_mismatch",
                "candidate_id": str(item.get("candidate_id", "")),
            })
    audit_ids = [str(item.get("candidate_id", "")) for item in audit]
    if len(audit_ids) != len(set(audit_ids)) or any(not identity for identity in audit_ids):
        errors.append({"code": "duplicate_or_missing_audit_candidate_id"})
    if require_promoted:
        if artifacts["audit"].get("audit_state") != "promoted_after_human_edge_audit":
            errors.append({"code": "promoted_audit_state_invalid"})
        if any(item.get("decision") not in {"approved", "rejected"} for item in audit):
            errors.append({"code": "promoted_audit_decisions_incomplete"})
        if any(not str(item.get("audit_note", "")).strip() for item in audit):
            errors.append({"code": "promoted_audit_notes_missing"})
        audit_by_occurrence = {
            (
                str(item.get("source_provision_id", "")),
                str(item.get("literal", "")),
                int(item.get("evidence", {}).get("start_offset", -1)),
            ): item
            for item in audit
            if isinstance(item.get("evidence"), dict)
        }
        if len(audit_by_occurrence) != len(audit):
            errors.append({"code": "promoted_audit_occurrences_ambiguous"})
        edge_occurrences = {
            (
                str(item.get("source_provision_id", "")),
                str(item.get("target_provision_id", "")),
                str(item.get("evidence", {}).get("text", "")),
                int(item.get("evidence", {}).get("start_offset", -1)),
            )
            for item in edges
            if isinstance(item.get("evidence"), dict)
        }
        unresolved_by_id = {
            str(item.get("candidate_id", "")): item
            for item in unresolved
        }
        for edge in edges:
            evidence = edge.get("evidence", {})
            occurrence = (
                str(edge.get("source_provision_id", "")),
                str(evidence.get("text", "")),
                int(evidence.get("start_offset", -1)),
            )
            audited = audit_by_occurrence.get(occurrence)
            if (
                audited is None
                or audited.get("decision") != "approved"
                or edge.get("target_provision_id") not in audited.get("target_provision_ids", [])
            ):
                errors.append({
                    "code": "promoted_edge_not_approved_by_audit",
                    "edge_id": str(edge.get("edge_id", "")),
                })
        for item in audit:
            candidate_identity = str(item.get("candidate_id", ""))
            evidence = item.get("evidence", {})
            source = str(item.get("source_provision_id", ""))
            literal = str(item.get("literal", ""))
            start = int(evidence.get("start_offset", -1)) if isinstance(evidence, dict) else -1
            expected_edges = {
                (source, str(target), literal, start)
                for target in item.get("target_provision_ids", [])
            }
            if item.get("decision") == "approved":
                if item.get("resolution") == "resolved" and not expected_edges.issubset(edge_occurrences):
                    errors.append({
                        "code": "approved_audit_edge_missing",
                        "candidate_id": candidate_identity,
                    })
            else:
                rejected = unresolved_by_id.get(candidate_identity)
                if rejected is None or rejected.get("reason_code") != "audit_rejected":
                    errors.append({
                        "code": "rejected_audit_unresolved_missing",
                        "candidate_id": candidate_identity,
                    })
                if any(
                    edge_source == source and edge_literal == literal and edge_start == start
                    for edge_source, _target, edge_literal, edge_start in edge_occurrences
                ):
                    errors.append({
                        "code": "rejected_audit_edge_present",
                        "candidate_id": candidate_identity,
                    })
    return {
        "valid": not errors,
        "errors": errors,
        "counts": {"provisions": len(provisions), "edges": len(edges), "unresolved": len(unresolved), "audit_candidates": len(audit)},
        "state": next(iter(states), None),
    }
