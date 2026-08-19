import json
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://example")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from agent.retrieval.reference_graph import (
    FollowOnceGuard,
    MAX_REFERENCE_EDGES,
    RetrievalReferenceContext,
    follow_published_references,
    follow_references_enabled,
    parse_feature_flag,
    should_follow_references,
)
from reference_graph.store import ReferenceGraphStore


ROOT = Path(__file__).resolve().parents[1]
CORPUS_DOCUMENT_ID = (
    "act-265-en-sha256-"
    "6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b"
)
EXTRACTION_ID = "extraction-sha256-fixture"


def _chunk(
    section: str,
    *,
    act: str = "265",
    document_id: str = CORPUS_DOCUMENT_ID,
    extraction_id: str = EXTRACTION_ID,
) -> dict:
    return {
        "act_number": act,
        "act_title": "EMPLOYMENT ACT 1955" if act == "265" else f"ACT {act}",
        "section_number": section,
        "content": f"Section {section} fixture text.",
        "language": "en",
        "page_number": 1,
        "page_start": 1,
        "page_end": 1,
        "pdf_url": "https://example.test/source.pdf#page=1",
        "document_id": document_id,
        "extraction_id": extraction_id,
    }


def _same_lookup(section: str, **kwargs) -> list[dict]:
    return [_chunk(
        section,
        act=kwargs["act_number"],
        document_id=kwargs["document_id"],
        extraction_id=kwargs["extraction_id"],
    )]


def _cross_lookup(section: str, *, act_number: str, **_kwargs) -> list[dict]:
    return [_chunk(
        section,
        act=act_number,
        document_id=f"act-{act_number}-en-sha256-target",
        extraction_id=f"extraction-{act_number}",
    )]


def _follow(**overrides):
    values = {
        "act": "Employment Act",
        "provision": "60D",
        "retrieved_chunks": [_chunk("60D")],
        "store": ReferenceGraphStore(ROOT / "data" / "reference_graph"),
        "same_act_lookup": _same_lookup,
        "cross_act_lookup": _cross_lookup,
    }
    values.update(overrides)
    return follow_published_references(**values)


def test_follow_flag_defaults_off_and_parses_only_explicit_true_values():
    assert parse_feature_flag(None) is False
    assert parse_feature_flag("") is False
    assert parse_feature_flag("unexpected") is False
    for value in ("1", "true", "TRUE", " yes ", "on"):
        assert parse_feature_flag(value) is True
    with patch.dict(os.environ, {}, clear=True):
        assert follow_references_enabled() is False


def test_internal_follow_does_not_depend_on_public_graph_exposure_flag():
    with patch.dict(os.environ, {
        "FOLLOW_REFERENCES_ENABLED": "on",
        "REFERENCE_GRAPH_ENABLED": "",
    }):
        result = _follow()
    assert result["status"] == "followed"
    assert result["metrics"]["edges_returned"] > 0


def test_selective_intent_gate_accepts_reference_questions_and_targeted_feedback_only():
    positives = [
        "What provisions does section 60D refer to?",
        "What is section 60D subject to?",
        "Which provisions refer to section 60D?",
        "What applies notwithstanding section 60D?",
        "Where is this definition located under another provision?",
        "Apakah peruntukan yang merujuk kepada seksyen 60D?",
    ]
    negatives = [
        "What does section 60D say?",
        "What are employee public holiday rights?",
        "Research employment law broadly.",
        "Tell me about the Holidays Act.",
    ]
    assert all(should_follow_references(query) for query in positives)
    assert not any(should_follow_references(query) for query in negatives)
    assert should_follow_references(
        "Retry the search.",
        "The answer missed a directly referenced provision.",
    )
    assert not should_follow_references(
        "Retry the search.",
        "The previous answer had an unsupported citation.",
    )


def test_once_guard_is_atomic():
    guard = FollowOnceGuard()
    assert guard.claim() is True
    assert guard.claim() is False


def test_store_scopes_section_edges_to_audited_descendants_without_second_hop():
    store = ReferenceGraphStore(ROOT / "data" / "reference_graph")
    exact = store.published_edges(
        CORPUS_DOCUMENT_ID,
        "act:265/section:60D",
        direction="outgoing",
    )
    scoped = store.published_edges(
        CORPUS_DOCUMENT_ID,
        "act:265/section:60D",
        direction="outgoing",
        include_descendants=True,
    )
    assert exact["edges"] == []
    assert any(
        edge["target_provision_id"] == "act:369/section:8"
        for edge in scoped["edges"]
    )
    assert all(
        edge["source_provision_id"].startswith("act:265/section:60D")
        for edge in scoped["edges"]
    )


def test_outgoing_follow_is_deterministic_hard_capped_and_hides_unresolved_candidates():
    first = _follow(max_edges=999)
    second = _follow(max_edges=999)

    assert first["status"] == "followed"
    assert first["edges"] == second["edges"]
    assert len(first["edges"]) == MAX_REFERENCE_EDGES
    assert first["metrics"]["edges_returned"] == MAX_REFERENCE_EDGES
    assert all(edge["relationship"] == "explicit_reference" for edge in first["edges"])
    assert all("literal" not in edge for edge in first["edges"])
    assert all("evidence_text" not in edge for edge in first["edges"])
    assert any(target["boundary"] for target in first["targets"])
    cross_act = next(
        chunk for chunk in first["chunks"]
        if chunk["act_number"] != "265"
    )
    assert (
        cross_act["_reference_context"]["provenance_scope"]
        == "version_neutral_cross_act_independent_corpus"
    )


def test_incoming_and_both_follow_only_direct_published_edges():
    incoming = _follow(direction="incoming")
    both = _follow(direction="both", max_edges=5)

    assert incoming["status"] == "followed"
    assert incoming["edges"]
    assert all(edge["direction"] == "incoming" for edge in incoming["edges"])
    assert all(
        edge["target_provision_id"].startswith("act:265/section:60D")
        for edge in incoming["edges"]
    )
    assert len(both["edges"]) <= MAX_REFERENCE_EDGES
    assert {edge["direction"] for edge in both["edges"]} == {"incoming", "outgoing"}


def test_relationship_filter_uses_only_published_literal_relationship_kinds():
    followed = _follow(relationship_kinds=["explicit_reference"])
    rejected = _follow(relationship_kinds=["subject_to"])

    assert followed["status"] == "followed"
    assert rejected["status"] == "skipped"
    assert rejected["reason"] == "invalid_relationship_kind"
    assert rejected["chunks"] == []


def test_exact_retrieved_document_and_extraction_anchor_is_mandatory():
    legacy = _follow(retrieved_chunks=[{
        "act_number": "265",
        "section_number": "60D",
        "document_id": None,
        "extraction_id": None,
    }])
    mismatch = _follow(document_id="act-265-en-sha256-other")
    ambiguous = _follow(retrieved_chunks=[
        _chunk("60D"),
        _chunk(
            "60D",
            document_id="act-265-en-sha256-other",
            extraction_id="extraction-other",
        ),
    ])

    for result in (legacy, mismatch, ambiguous):
        assert result["status"] == "skipped"
        assert result["reason"] == "exact_anchor_identity_unavailable"
        assert result["metrics"]["skipped"] == 1


def test_graph_snapshot_mismatch_fails_open_without_target_lookup():
    class MismatchedStore:
        def document(self, _document_id):
            return {"corpus_document_id": "different", "act_number": "265"}

        def published_edges(self, *_args, **_kwargs):
            raise AssertionError("must not query mismatched graph")

    result = _follow(store=MismatchedStore())
    assert result["status"] == "skipped"
    assert result["reason"] == "graph_snapshot_corpus_mismatch"
    assert result["metrics"]["fail_open"] == 1
    assert result["chunks"] == []


def test_missing_and_malformed_promoted_graphs_fail_open(tmp_path: Path):
    missing = _follow(store=ReferenceGraphStore(tmp_path))
    assert missing["status"] == "graph_unavailable"
    assert missing["reason"] == "not_indexed"

    malformed_root = tmp_path / "malformed"
    directory = malformed_root / CORPUS_DOCUMENT_ID
    directory.mkdir(parents=True)
    (directory / "provisions.json").write_text("{not-json", encoding="utf-8")
    for name in ("edges.json", "unresolved.json", "audit.json"):
        (directory / name).write_text(json.dumps({}), encoding="utf-8")

    malformed = _follow(store=ReferenceGraphStore(malformed_root))
    assert malformed["status"] == "graph_unavailable"
    assert malformed["reason"] == "malformed_or_unavailable"
    assert malformed["metrics"]["fail_open"] == 1
    assert malformed["chunks"] == []


def test_target_lookup_failure_is_recorded_and_does_not_inject_graph_text():
    def failed_lookup(*_args, **_kwargs):
        raise RuntimeError("corpus unavailable")

    result = _follow(
        same_act_lookup=failed_lookup,
        cross_act_lookup=failed_lookup,
        max_edges=3,
    )
    assert result["status"] == "followed"
    assert result["chunks"] == []
    assert result["metrics"]["targets_failed"] > 0
    assert result["metrics"]["fail_open"] == 1
    assert all(
        target["lookup_status"] == "not_found_in_compatible_corpus"
        for target in result["targets"]
    )


def test_cross_act_legacy_lookup_result_is_not_accepted_as_provenance():
    def legacy_cross(section: str, *, act_number: str):
        return [_chunk(
            section,
            act=act_number,
            document_id="",
            extraction_id="",
        )]

    result = _follow(cross_act_lookup=legacy_cross, max_edges=3)
    cross_target = next(
        target for target in result["targets"]
        if target["provision_id"].startswith("act:369/")
    )
    assert cross_target["boundary"] is True
    assert cross_target["lookup_status"] == "not_found_in_compatible_corpus"
    assert all(chunk["act_number"] != "369" for chunk in result["chunks"])


def test_target_lookup_identity_mismatch_cannot_be_silently_conflated():
    def wrong_same(section: str, **_kwargs):
        return [_chunk(
            section,
            document_id="different-document",
            extraction_id="different-extraction",
        )]

    def wrong_cross(section: str, *, act_number: str):
        return [_chunk(
            section,
            act="999",
            document_id=f"act-{act_number}-mislabelled",
            extraction_id="mislabelled-extraction",
        )]

    result = _follow(
        same_act_lookup=wrong_same,
        cross_act_lookup=wrong_cross,
        max_edges=3,
    )
    assert result["chunks"] == []
    assert result["metrics"]["targets_resolved"] == 0
    assert result["metrics"]["targets_failed"] == len(result["targets"])
    assert result["metrics"]["fail_open"] == 1
