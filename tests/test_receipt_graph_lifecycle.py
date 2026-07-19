from agent.graph import _record_turn


def test_fail_closed_delivery_strips_evidence_from_rejected_draft():
    citation = {
        "act_number": "56",
        "act_title": "EVIDENCE ACT 1950",
        "section_number": "90A",
        "pdf_url": "https://example.test/official.pdf",
        "page_number": 72,
        "receipt": {
            "document_id": "act-56-reprint-2017-c11400ad",
            "evidence": [{"claim": "Rejected claim", "quote": "Rejected quote"}],
        },
    }
    state = {
        "query": "Question",
        "draft_response": "Rejected draft",
        "final_response": "Safe fallback",
        "citations": [citation],
        "violations": ["Grounding violation"],
    }

    result = _record_turn(state)

    assert "properly cited answer" in result["final_response"]
    assert result["final_response"] != state["draft_response"]
    assert result["citations"][0]["receipt"]["document_id"] == citation["receipt"]["document_id"]
    assert result["citations"][0]["receipt"]["evidence"] == []
