import json
from dataclasses import asdict
from pathlib import Path

import pytest

from reference_graph.artifacts import (
    apply_audit_decisions,
    artifact_hashes,
    candidate_dir,
    load_artifacts,
    promote,
    write_candidate,
)
from reference_graph.audit import audit_report, decision_template
from reference_graph.build import build_graph
from reference_graph.cli import main as reference_graph_cli
from reference_graph.loader import apply_migrations, load_promoted, verify_database
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
from reference_graph.pdf_text import PdfPage, PdfText
from reference_graph.provisions import page_groups
from reference_graph.reference_lexer import lex
from reference_graph.store import GraphNotIndexed, ReferenceGraphStore
from reference_graph.validation import validate_artifacts


ROOT = Path(__file__).resolve().parents[1]
SEPTEMBER_DOCUMENT_ID = (
    "act-265-en-sha256-"
    "6ef0ba72dc9c149c474d7989b8c3b39168c753472d11a64d720bd227e12a3bf7"
)


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

    # Generalization must not alter the already audited February parser output.
    promoted = load_artifacts(ROOT / "data" / "reference_graph" / GRAPH_DOCUMENT_ID)
    assert promoted["provisions"]["document"] == asdict(document)
    assert promoted["provisions"]["provisions"] == [item.to_dict() for item in provisions]
    stripped_audit = [
        {key: value for key, value in item.items() if key not in {"decision", "audit_note"}}
        for item in promoted["audit"]["candidates"]
    ]
    assert stripped_audit == [item.to_dict() for item in candidates]
    approved_occurrences = {
        (
            item["source_provision_id"],
            item["literal"],
            item["evidence"]["start_offset"],
        )
        for item in promoted["audit"]["candidates"]
        if item["decision"] == "approved"
    }
    approved_edges = [
        item.to_dict()
        for item in edges
        if (
            item.source_provision_id,
            item.evidence.text,
            item.evidence.start_offset,
        ) in approved_occurrences
    ]
    assert promoted["edges"]["edges"] == approved_edges


def test_september_2023_snapshot_parser_goldens_are_receipt_bound():
    document, provisions, edges, unresolved, candidates = build_graph(ROOT, SEPTEMBER_DOCUMENT_ID)
    assert document.sha256 == "6ef0ba72dc9c149c474d7989b8c3b39168c753472d11a64d720bd227e12a3bf7"
    assert document.page_count == 121
    assert document.receipt_path == f"/receipts/{SEPTEMBER_DOCUMENT_ID}/pdf"
    assert (len(provisions), len(edges), len(unresolved), len(candidates)) == (634, 342, 72, 385)

    by_id = {item.provision_id: item for item in provisions}
    assert (by_id["act:265/section:25A"].page_start, by_id["act:265/section:25A"].page_end) == (35, 36)
    assert (by_id["act:265/section:60D"].page_start, by_id["act:265/section:60D"].page_end) == (57, 59)
    assert (by_id["act:265/schedule:first"].page_start, by_id["act:265/schedule:first"].page_end) == (107, 109)
    assert (by_id["act:265/schedule:second"].page_start, by_id["act:265/schedule:second"].page_end) == (109, 110)
    cross_act = next(edge for edge in edges if edge.target_provision_id == "act:369/section:8")
    assert cross_act.source_provision_id == "act:265/section:60D/subsection:1/paragraph:b"
    assert cross_act.target_version_id is None
    assert cross_act.evidence.pages[0].page_number == 57


def test_dynamic_page_groups_handle_a_representative_older_layout():
    pages = [
        PdfPage(1, "Cover", 100, 100, []),
        PdfPage(2, "An Act relating to employment.\n1. Short title", 100, 100, []),
        PdfPage(3, "2. Interpretation", 100, 100, []),
        PdfPage(4, "FIRST SCHEDULE", 100, 100, []),
        PdfPage(5, "Schedule content", 100, 100, []),
        PdfPage(6, "LIST OF AMENDMENTS", 100, 100, []),
    ]
    document = SourceDocument(
        "act-265-en-sha256-older", "act-265-en-sha256-older", "265", "EMPLOYMENT ACT 1955",
        "en", "c" * 64, len(pages), "/receipts/act-265-en-sha256-older/pdf",
        "data/pdfs/objects/older.pdf", "data/pdfs/manifest.json",
    )
    groups = page_groups(PdfText(pages), document)
    assert [page.page_number for page in groups.main] == [2, 3]
    assert [page.page_number for page in groups.schedules] == [4, 5]


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


def test_graph_document_ids_cannot_escape_the_artifact_root(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid_graph_document_id"):
        candidate_dir(tmp_path, "../escape")


def test_failed_registered_snapshot_build_writes_an_explicit_blocked_report(tmp_path: Path):
    document_id = "act-265-en-sha256-missing"
    assert reference_graph_cli([
        "--root", str(tmp_path),
        "--document-id", document_id,
        "build",
    ]) == 1
    report = json.loads(
        (candidate_dir(tmp_path, document_id) / "build-report.json").read_text()
    )
    assert report == {
        "document_id": document_id,
        "error_class": "CorpusDocumentNotFound",
        "reason": f"'{document_id}'",
        "stage": "registered_pdf_parse",
        "status": "blocked",
    }


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
    target_id = stable_id("265", ("section", "69"))
    target = Provision(
        target_id, versioned_id(document.document_id, target_id), "section", "Section 69",
        stable_id("265"), "section 69", 0, 10, 90, 90,
    )
    evidence = Evidence("section 69", 0, 10, [PageProvenance(22, [Rectangle(0.1, 0.1, 0.2, 0.02)])])
    cid = candidate_id(provision_id, 0, evidence.text)
    edge = Edge(edge_id(provision_id, "act:265/section:69", 0, evidence.text), provision_id, provision.version_id,
                "act:265/section:69", versioned_id(document.document_id, "act:265/section:69"),
                "explicit_reference", "section", evidence)
    candidate = Candidate(cid, provision_id, provision.version_id, evidence.text, "section", [edge.target_provision_id], "resolved", None, evidence)
    write_candidate(tmp_path, document, [provision, target], [edge], [], [candidate])
    return document, cid


def test_promotion_is_blocked_until_complete_human_decisions(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    with pytest.raises(ValueError, match="human_edge_audit_required"):
        promote(tmp_path, document.document_id)
    with pytest.raises(ValueError, match="audit_decision_or_note_invalid"):
        apply_audit_decisions(
            tmp_path,
            document.document_id,
            {cid: {"decision": "approved", "audit_note": ""}},
        )
    apply_audit_decisions(tmp_path, document.document_id, {cid: {"decision": "approved", "audit_note": "receipt checked"}})
    assert validate_artifacts(promote(tmp_path, document.document_id), require_promoted=True)["valid"]


def test_audit_decision_template_is_complete_receipt_bound_and_never_preapproved(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    template = decision_template(tmp_path, document.document_id)
    assert template["receipt_path"] == document.receipt_path
    assert set(template["decisions"]) == {cid}
    item = template["decisions"][cid]
    assert item["decision"] == ""
    assert item["audit_note"] == ""
    assert item["review_context"]["target_provision_ids"] == ["act:265/section:69"]


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
    assert counts == {"provisions": 2, "edges": 1, "unresolved": 0, "audit_candidates": 1}
    assert connection.transactions == 1
    assert not any("chunks" in command.casefold() for command in connection.cursor_value.commands)
    assert any("ON CONFLICT" in command for command in connection.cursor_value.commands)
    assert any("artifact_hashes" in command for command in connection.cursor_value.commands)


def test_database_migrations_and_artifact_verification_are_additive_and_consistent(tmp_path: Path):
    class MigrationCursor:
        def __init__(self): self.commands: list[str] = []
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, _params=None): self.commands.append(str(sql))

    class MigrationConnection:
        def __init__(self): self.cursor_value = MigrationCursor()
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def cursor(self): return self.cursor_value

    migration_connection = MigrationConnection()
    assert apply_migrations(migration_connection) == [
        "0001_reference_graph.sql",
        "0002_reference_graph_artifact_identity.sql",
    ]
    migration_sql = "\n".join(migration_connection.cursor_value.commands).casefold()
    assert "drop table" not in migration_sql
    assert "truncate" not in migration_sql
    assert all(statement not in migration_sql for statement in (
        "insert into chunks",
        "update chunks",
        "delete from chunks",
        "alter table chunks",
        "drop table chunks",
    ))

    document, cid = _small_audited_graph(tmp_path)
    apply_audit_decisions(
        tmp_path,
        document.document_id,
        {cid: {"decision": "approved", "audit_note": "receipt checked"}},
    )
    directory = promote(tmp_path, document.document_id)
    expected_hashes = artifact_hashes(directory)

    class VerifyCursor:
        def __init__(self): self.row = None
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, _params=None):
            normalized = " ".join(str(sql).split())
            if "reference_graph_provisions" in normalized:
                self.row = (2,)
            elif "reference_graph_edges" in normalized:
                self.row = (1,)
            elif "reference_graph_unresolved" in normalized:
                self.row = (0,)
            else:
                self.row = (expected_hashes,)
        def fetchone(self): return self.row

    class VerifyConnection:
        def cursor(self): return VerifyCursor()

    result = verify_database(
        VerifyConnection(),
        document.document_id,
        root=tmp_path,
    )
    assert result["valid"]
    assert result["artifact_hashes"] == expected_hashes


def test_phase1_alias_and_promoted_snapshots_resolve_while_candidates_stay_hidden():
    root = ROOT / "data" / "reference_graph"
    store = ReferenceGraphStore(root)
    corpus_document_id = "act-265-en-sha256-6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b"
    assert store.status(corpus_document_id)["status"] == "available"
    neighborhood = store.neighborhood(corpus_document_id, "act:265/section:60D")
    assert neighborhood["status"] == "available"
    snapshots = store.available_snapshots(act_number="265", language="en")
    assert [item["document_id"] for item in snapshots] == [
        "act-265-en-sha256-aaeb175a7c6986b6d535da37680c05535597c09ec0f5813233ec779c986f7caa",
        "act-265-en-sha256-1ee65655aedadc7d1ea2e47526036106149835583d246e61d3de3d10749e1b95",
        GRAPH_DOCUMENT_ID,
        "act-265-en-sha256-6ef0ba72dc9c149c474d7989b8c3b39168c753472d11a64d720bd227e12a3bf7",
    ]
    february = next(item for item in snapshots if item["document_id"] == GRAPH_DOCUMENT_ID)
    assert february["corpus_document_id"] == corpus_document_id


def test_multi_document_candidates_are_isolated_and_hash_deterministically(tmp_path: Path):
    document, cid = _small_audited_graph(tmp_path)
    first = candidate_dir(tmp_path, document.document_id)
    first_hashes = artifact_hashes(first)
    other = SourceDocument(
        "act-265-en-sha256-other", "act-265-en-sha256-other", "265", "EMPLOYMENT ACT 1955",
        "en", "b" * 64, 1, "/receipts/act-265-en-sha256-other/pdf",
        "data/pdfs/objects/other.pdf", "data/pdfs/manifest.json",
    )
    provision_id = stable_id("265", ("section", "4"))
    provision = Provision(
        provision_id, versioned_id(other.document_id, provision_id), "section", "Section 4",
        stable_id("265"), "section 4", 0, 9, 1, 1,
    )
    write_candidate(tmp_path, other, [provision], [], [], [])
    assert candidate_dir(tmp_path, other.document_id) != first
    assert artifact_hashes(first) == first_hashes
    assert (candidate_dir(tmp_path, other.document_id) / "provisions.json").is_file()
    assert cid


def test_human_audit_blocks_candidate_load_and_store_exposure(tmp_path: Path):
    document, _cid = _small_audited_graph(tmp_path)
    with pytest.raises(ValueError, match="cannot_load_invalid_reference_graph"):
        load_promoted(object(), tmp_path, document.document_id)
    with pytest.raises(GraphNotIndexed):
        ReferenceGraphStore(tmp_path).status(document.document_id)


def test_store_reports_every_focus_presence_combination_explicitly(tmp_path: Path):
    base, cid = _small_audited_graph(tmp_path)
    apply_audit_decisions(
        tmp_path,
        base.document_id,
        {cid: {"decision": "approved", "audit_note": "receipt checked"}},
    )
    promote(tmp_path, base.document_id)

    compare = SourceDocument(
        "act-265-en-sha256-compare", "act-265-en-sha256-compare", "265", "EMPLOYMENT ACT 1955",
        "en", "d" * 64, 1, "/receipts/act-265-en-sha256-compare/pdf",
        "data/pdfs/objects/compare.pdf", "data/pdfs/manifest.json",
    )
    provision_id = stable_id("265", ("section", "69"))
    provision = Provision(
        provision_id, versioned_id(compare.document_id, provision_id), "section", "Section 69",
        stable_id("265"), "section 69", 0, 10, 1, 1,
    )
    write_candidate(tmp_path, compare, [provision], [], [], [])
    promote(tmp_path, compare.document_id)
    store = ReferenceGraphStore(tmp_path)

    missing_compare = store.compare(base.document_id, compare.document_id, "act:265/section:4")
    assert missing_compare["status"] == "focus_missing_compare"
    assert missing_compare["focus_presence"] == {"base": True, "compare": False}
    missing_base = store.compare(compare.document_id, base.document_id, "act:265/section:4")
    assert missing_base["status"] == "focus_missing_base"
    assert missing_base["focus_presence"] == {"base": False, "compare": True}
    missing_both = store.compare(base.document_id, compare.document_id, "act:265/section:5")
    assert missing_both["status"] == "focus_missing_base"
    assert missing_both["focus_presence"] == {"base": False, "compare": False}
    assert missing_both["missing_focus_documents"] == ["base", "compare"]
