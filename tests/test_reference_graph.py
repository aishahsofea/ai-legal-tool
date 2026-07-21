import json
from pathlib import Path

import pytest

from reference_graph.artifacts import (
    apply_audit_decisions,
    candidate_dir,
    load_artifacts,
    promote,
    write_candidate,
)
from reference_graph.audit import audit_report
from reference_graph.build import build_graph
from reference_graph.loader import load_promoted
from reference_graph.models import (
    Candidate,
    Edge,
    Evidence,
    GRAPH_DOCUMENT_ID,
    PageProvenance,
    Provision,
    Rectangle,
    SourceDocument,
    candidate_id,
    edge_id,
    stable_id,
    versioned_id,
)
from reference_graph.reference_lexer import lex
from reference_graph.validation import validate_artifacts


ROOT = Path(__file__).resolve().parents[1]


def _graph():
    return build_graph(ROOT)


def test_act_265_goldens_are_deterministic_and_receipt_bound(tmp_path: Path):
    document, provisions, edges, unresolved, candidates = _graph()
    assert document.document_id == GRAPH_DOCUMENT_ID
    assert document.sha256 == "6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b"
    assert document.page_count == 127
    assert document.receipt_path == "/receipts/act-265-reprint-2023-6fec2f07/pdf"
    by_id = {item.provision_id: item for item in provisions}
    assert by_id["act:265/section:25A"].page_start == 37
    assert by_id["act:265/section:25A"].page_end == 38
    assert by_id["act:265/schedule:first"].page_start == 112
    assert by_id["act:265/schedule:first"].page_end == 113
    assert by_id["act:265/schedule:second"].page_start == 113
    assert by_id["act:265/schedule:second"].page_end == 115

    pairs = {(edge.source_provision_id, edge.target_provision_id) for edge in edges}
    assert ("act:265/section:25A/subsection:1", "act:265/section:25/subsection:1") in pairs
    assert ("act:265/section:4", "act:265/section:69") in pairs
    assert ("act:265/section:4", "act:265/section:73") in pairs
    assert ("act:265/section:60D/subsection:1/paragraph:b", "act:369/section:8") in pairs
    assert any(source.startswith("act:265/section:60K/") and target == "act:446" for source, target in pairs)
    act_369_edge = next(edge for edge in edges if edge.target_provision_id == "act:369/section:8")
    assert act_369_edge.evidence.pages[0].page_number == 60
    assert act_369_edge.evidence.pages[0].rectangles
    assert all(candidate.evidence.pages and candidate.evidence.pages[0].rectangles for candidate in candidates)

    work = write_candidate(tmp_path, document, provisions, edges, unresolved, candidates)
    result = validate_artifacts(work)
    assert result["valid"]
    report = audit_report(tmp_path, GRAPH_DOCUMENT_ID)
    assert report["manual_gate_required"]
    assert report["pending_count"] == len(candidates)


def test_lexer_rejects_partial_words_and_keeps_explicit_forms_only():
    candidates = lex("The matter is under this Act, if it applies. See section 8 of the Holidays Act 1951 [Act 369].")
    assert [(item.kind, item.literal) for item in candidates] == [
        ("act", "this Act"),
        ("section", "section 8 of the Holidays Act 1951 [Act 369]"),
    ]


def test_lexer_rejects_structural_part_headings_but_keeps_part_references():
    assert lex("\nPART IV\n") == []
    assert [(item.kind, item.literal) for item in lex("A deduction allowed under Part IV remains lawful.")] == [
        ("part", "Part IV"),
    ]


def test_candidate_artifacts_stay_in_work_directory_and_are_not_promoted(tmp_path: Path):
    document, provisions, edges, unresolved, candidates = _graph()
    work = write_candidate(tmp_path, document, provisions, edges, unresolved, candidates)
    assert work == candidate_dir(tmp_path, GRAPH_DOCUMENT_ID)
    assert not (tmp_path / GRAPH_DOCUMENT_ID / "edges.json").exists()
    assert validate_artifacts(work, require_promoted=True)["valid"] is False


def test_checked_in_schema_contract_rejects_a_missing_edge_relationship(tmp_path: Path):
    document, provisions, edges, unresolved, candidates = _graph()
    work = write_candidate(tmp_path, document, provisions, edges, unresolved, candidates)
    edges_path = work / "edges.json"
    payload = json.loads(edges_path.read_text())
    del payload["edges"][0]["relationship"]
    edges_path.write_text(json.dumps(payload))
    assert any(error["code"] == "schema_item_required_missing" for error in validate_artifacts(work)["errors"])


def _small_audited_graph(tmp_path: Path):
    document = SourceDocument(
        GRAPH_DOCUMENT_ID, "act-265-en-sha256-fixture", "265", "EMPLOYMENT ACT 1955", "en", "a" * 64, 127,
        f"/receipts/{GRAPH_DOCUMENT_ID}/pdf", "data/pdfs/en/265.pdf", "data/pdfs/manifest.json",
    )
    provision_id = stable_id("265", ("section", "4"))
    provision = Provision(provision_id, versioned_id(document.document_id, provision_id), "section", "Section 4",
                          stable_id("265"), "section 4", 0, 9, 22, 22)
    evidence = Evidence("section 69", 0, 10, [PageProvenance(22, [Rectangle(0.1, 0.1, 0.2, 0.02)])])
    cid = candidate_id(provision_id, 0, evidence.text)
    edge = Edge(edge_id(provision_id, "act:265/section:69", 0, evidence.text), provision_id, provision.version_id,
                "act:265/section:69", versioned_id(document.document_id, "act:265/section:69"),
                "explicit_reference", "section", evidence)
    candidate = Candidate(cid, provision_id, provision.version_id, evidence.text, "section", [edge.target_provision_id], "resolved", None, evidence)
    write_candidate(tmp_path, document, [provision], [edge], [], [candidate])
    return document, cid


def test_promotion_is_blocked_until_complete_human_decisions(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    with pytest.raises(ValueError, match="human_edge_audit_required"):
        promote(tmp_path, document.document_id)
    apply_audit_decisions(tmp_path, document.document_id, {cid: {"decision": "approved", "audit_note": "receipt checked"}})
    assert validate_artifacts(promote(tmp_path, document.document_id), require_promoted=True)["valid"]


def test_rejected_audited_edge_becomes_one_audit_unresolved_record(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    apply_audit_decisions(tmp_path, document.document_id, {cid: {"decision": "rejected", "audit_note": "receipt differs"}})
    promoted = load_artifacts(promote(tmp_path, document.document_id))
    assert promoted["edges"]["edges"] == []
    assert promoted["unresolved"]["unresolved"] == [{
        "candidate_id": cid,
        "source_provision_id": "act:265/section:4",
        "source_version_id": f"{GRAPH_DOCUMENT_ID}/provision:act:265/section:4",
        "literal": "section 69",
        "reference_kind": "section",
        "reason_code": "audit_rejected",
        "evidence": {
            "text": "section 69", "start_offset": 0, "end_offset": 10,
            "pages": [{"page_number": 22, "rectangles": [{"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.02}]}],
        },
    }]


def test_loader_is_transactional_idempotent_and_never_touches_chunks(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    apply_audit_decisions(tmp_path, document.document_id, {cid: {"decision": "approved", "audit_note": "receipt checked"}})
    promote(tmp_path, document.document_id)

    class Cursor:
        def __init__(self): self.commands: list[str] = []
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, _params=None): self.commands.append(" ".join(str(sql).split()))

    class Connection:
        def __init__(self): self.cursor_value = Cursor(); self.transactions = 0
        def __enter__(self): self.transactions += 1; return self
        def __exit__(self, *_args): return False
        def cursor(self): return self.cursor_value

    connection = Connection()
    counts = load_promoted(connection, tmp_path, document.document_id)
    assert counts == {"provisions": 1, "edges": 1, "unresolved": 0, "audit_candidates": 1}
    assert connection.transactions == 1
    assert not any("chunks" in command.casefold() for command in connection.cursor_value.commands)
    assert any("ON CONFLICT" in command for command in connection.cursor_value.commands)
