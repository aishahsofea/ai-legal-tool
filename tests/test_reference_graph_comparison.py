from copy import deepcopy

from reference_graph.comparison import (
    compare_neighborhoods,
    logical_reference_key,
)


def _edge(identity: str, literal: str, start: int, *, target: str = "act:265/section:4"):
    return {
        "edge_id": identity,
        "source_provision_id": "act:265/section:60D",
        "target_provision_id": target,
        "relationship": "explicit_reference",
        "reference_kind": "section",
        "evidence": {
            "text": literal,
            "start_offset": start,
            "end_offset": start + len(literal),
            "pages": [{"page_number": 60, "rectangles": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}]}],
        },
    }


def _neighborhood(edges):
    return {
        "status": "available",
        "nodes": [{
            "provision_id": "act:265/section:60D",
            "version_id": "document/provision:act:265/section:60D",
            "label": "Section 60D",
            "kind": "section",
            "page_start": 60,
            "page_end": 63,
        }],
        "edges": edges,
    }


def test_logical_key_ignores_document_offsets_and_edge_ids():
    first = _edge("edge:first", "section   4", 10)
    second = _edge("edge:second", "SECTION 4", 800)
    assert logical_reference_key(first) == logical_reference_key(second)


def test_comparison_preserves_duplicate_multisets_and_independent_evidence():
    base_edges = [_edge("edge:base-1", "section 4", 10), _edge("edge:base-2", "section 4", 40)]
    compare_edges = [_edge("edge:compare-1", "section 4", 900)]
    result = compare_neighborhoods(
        _neighborhood(base_edges),
        _neighborhood(compare_edges),
        base_document_id="base",
        compare_document_id="compare",
        focus_provision_id="act:265/section:60D",
    )
    assert result["counts"] == {"added": 0, "removed": 1, "unchanged": 1}
    assert [item["occurrence_ordinal"] for item in result["references"]] == [1, 2]
    unchanged = next(item for item in result["references"] if item["status"] == "unchanged")
    assert unchanged["base_edge"]["evidence"]["start_offset"] == 10
    assert unchanged["compare_edge"]["evidence"]["start_offset"] == 900


def test_literal_wording_change_is_removed_plus_added():
    result = compare_neighborhoods(
        _neighborhood([_edge("edge:base", "section 4", 10)]),
        _neighborhood([_edge("edge:compare", "sections 4 and 5", 10)]),
        base_document_id="base",
        compare_document_id="compare",
        focus_provision_id="act:265/section:60D",
    )
    assert result["counts"] == {"added": 1, "removed": 1, "unchanged": 0}
    assert {item["status"] for item in result["references"]} == {"added", "removed"}


def test_comparison_does_not_copy_evidence_between_snapshots():
    base = _edge("edge:base", "section 4", 10)
    compare = deepcopy(base)
    compare["edge_id"] = "edge:compare"
    compare["evidence"]["pages"][0]["page_number"] = 99
    result = compare_neighborhoods(
        _neighborhood([base]),
        _neighborhood([compare]),
        base_document_id="base",
        compare_document_id="compare",
        focus_provision_id="act:265/section:60D",
    )
    reference = result["references"][0]
    assert reference["base_edge"]["evidence"]["pages"][0]["page_number"] == 60
    assert reference["compare_edge"]["evidence"]["pages"][0]["page_number"] == 99
