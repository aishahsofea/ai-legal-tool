import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import pytest
from fastapi.testclient import TestClient

from api.main import app
from citation_receipts.locator import contains_normalized_sequence, locate_evidence, normalized_tokens
from citation_receipts.registry import (
    DEFAULT_MANIFEST_PATH,
    ReceiptDocumentIntegrityError,
    ReceiptDocumentNotFound,
    ReceiptManifestError,
    ReceiptRegistry,
)
from corpus.storage import CdnCorpusStorage


def _write_pdf(path: Path, page_lines: list[list[str]]) -> None:
    document = fitz.open()
    for lines in page_lines:
        page = document.new_page(width=400, height=500)
        for index, line in enumerate(lines):
            page.insert_text((40, 60 + index * 30), line, fontsize=12)
    document.save(path)
    document.close()


def _fixture_registry(tmp_path: Path) -> tuple[ReceiptRegistry, Path, str]:
    pdf_path = tmp_path / "en" / "fixture.pdf"
    pdf_path.parent.mkdir()
    _write_pdf(pdf_path, [
        ["Alpha evidence appears here.", "A computa-", "tion record follows."],
        ["Cross page matching succeeds.", "repeat this phrase; repeat this phrase."],
    ])
    data = pdf_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    document_id = f"fixture-{digest[:8]}"
    manifest = {
        "schema_version": 1,
        "documents": [{
            "document_id": document_id,
            "act_number": "999",
            "act_title": "FIXTURE ACT",
            "language": "en",
            "asset_path": "en/fixture.pdf",
            "sha256": digest,
            "byte_size": len(data),
            "page_count": 2,
            "source_url": "https://example.test/fixture.pdf",
            "timeline_date": "2026-01-01",
            "timeline_type": "REPRINT ONLINE",
            "metadata_scraped_at": "2026-01-02T00:00:00+00:00",
        }],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return ReceiptRegistry(manifest_path), pdf_path, document_id


def test_production_manifest_registers_full_corpus_and_validates_active_pilots():
    registry = ReceiptRegistry(DEFAULT_MANIFEST_PATH)

    assert len(registry.documents) == 601
    assert set(registry.documents_by_act) == {"56", "265", "574", "709", "777"}
    assert {
        document.act_number for document in registry.documents.values() if document.language == "bm"
    } == {"144", "152", "194", "220", "228", "230"}
    for document in registry.documents_by_act.values():
        path = registry.validate(document)
        assert path.stat().st_size == document.byte_size
        assert hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
        with fitz.open(path) as pdf:
            assert pdf.page_count == document.page_count
            assert all(page.rotation == 0 for page in pdf)
            assert all((page.cropbox.x0, page.cropbox.y0) == (0, 0) for page in pdf)


def test_manifest_rejects_path_escape(tmp_path: Path):
    manifest = {
        "schema_version": 1,
        "documents": [{
            "document_id": "escape",
            "act_number": "1",
            "act_title": "ESCAPE",
            "language": "en",
            "asset_path": "../outside.pdf",
            "sha256": "0" * 64,
            "byte_size": 1,
            "page_count": 1,
            "source_url": "https://example.test",
            "timeline_date": "2026-01-01",
            "timeline_type": "REPRINT",
            "metadata_scraped_at": "2026-01-01T00:00:00Z",
        }],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ReceiptManifestError):
        ReceiptRegistry(path)


def test_corrupt_known_document_is_unavailable(tmp_path: Path):
    registry, pdf_path, _ = _fixture_registry(tmp_path)
    document = registry.for_act("999")
    assert document is not None
    pdf_path.write_bytes(pdf_path.read_bytes() + b"changed")

    with pytest.raises(ReceiptDocumentIntegrityError):
        registry.validate(document)
    assert registry.validated_for_act("999") is None


def test_strict_normalization_and_line_end_dehyphenation(tmp_path: Path):
    registry, pdf_path, _ = _fixture_registry(tmp_path)
    document = registry.for_act("999")
    assert document is not None
    registry.validate(document)

    assert normalized_tokens("‘Alpha’\u00ad — EVIDENCE") == ["alpha", "evidence"]
    assert contains_normalized_sequence("alpha evidence", "... Alpha   evidence!")
    result = locate_evidence(pdf_path, "a computation record", 1)
    assert result.status == "matched"
    assert result.pages[0].page_number == 1
    assert all(0 <= value <= 1 for rectangle in result.pages[0].rectangles for value in (
        rectangle.x, rectangle.y, rectangle.width, rectangle.height
    ))


def test_cross_page_match_groups_rectangles_by_page(tmp_path: Path):
    registry, pdf_path, _ = _fixture_registry(tmp_path)
    result = locate_evidence(pdf_path, "record follows cross page matching", 1)

    assert result.status == "matched"
    assert [page.page_number for page in result.pages] == [1, 2]
    assert all(page.rectangles for page in result.pages)


def test_ambiguous_and_not_found_never_return_highlights(tmp_path: Path):
    _registry, pdf_path, _ = _fixture_registry(tmp_path)

    ambiguous = locate_evidence(pdf_path, "repeat this phrase", 1)
    missing = locate_evidence(pdf_path, "words that are absent", 1)
    empty = locate_evidence(pdf_path, None, 2)

    assert (ambiguous.status, ambiguous.pages) == ("ambiguous", [])
    assert (missing.status, missing.pages) == ("not_found", [])
    assert (empty.status, empty.fallback_page, empty.pages) == ("not_found", 2, [])


@pytest.mark.parametrize(("act_number", "start_page", "quote"), [
    ("56", 72, "In any criminal or civil proceeding a document produced by a computer"),
    ("265", 30, "not later than the seventh day after the last day of any wage period"),
    ("574", 42, "When a criminal act is done by several persons, in furtherance of the common intention of all"),
    ("709", 23, "A data subject shall be given access to his personal data held by a data user"),
    ("777", 157, "Before a distribution is made by a company to any shareholder, such distribution shall be authorized by the directors of the company"),
])
def test_real_five_act_locator_integration(act_number: str, start_page: int, quote: str):
    registry = ReceiptRegistry(DEFAULT_MANIFEST_PATH)
    document = registry.for_act(act_number)
    assert document is not None

    result = locate_evidence(registry.validate(document), quote, start_page)

    assert result.status == "matched"
    assert result.pages[0].page_number == start_page
    assert result.pages[0].rectangles


def test_pdf_endpoint_returns_identity_headers_range_and_exact_bytes(tmp_path: Path):
    registry, pdf_path, document_id = _fixture_registry(tmp_path)
    with patch("api.receipts.get_receipt_registry", return_value=registry):
        client = TestClient(app)
        response = client.get(f"/receipts/{document_id}/pdf")
        partial = client.get(f"/receipts/{document_id}/pdf", headers={"Range": "bytes=0-15"})

    document = registry.get(document_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["etag"] == f'"{document.sha256}"'
    assert "immutable" in response.headers["cache-control"]
    assert response.content == pdf_path.read_bytes()
    assert partial.status_code == 206
    assert partial.content == pdf_path.read_bytes()[:16]


def test_pdf_head_conditional_ranges_and_cors(tmp_path: Path):
    registry, pdf_path, document_id = _fixture_registry(tmp_path)
    document = registry.get(document_id)
    with patch("api.receipts.get_receipt_registry", return_value=registry):
        client = TestClient(app)
        head = client.head(f"/receipts/{document_id}/pdf")
        cached = client.get(
            f"/receipts/{document_id}/pdf",
            headers={"If-None-Match": f'"{document.sha256}"'},
        )
        suffix = client.get(f"/receipts/{document_id}/pdf", headers={"Range": "bytes=-8"})
        invalid = client.get(f"/receipts/{document_id}/pdf", headers={"Range": "bytes=999999-"})
        cors = client.options(
            f"/receipts/{document_id}/pdf",
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": "HEAD",
                "Access-Control-Request-Headers": "Range,If-None-Match",
            },
        )

    assert head.status_code == 200
    assert head.content == b""
    assert int(head.headers["content-length"]) == document.byte_size
    assert cached.status_code == 304 and cached.content == b""
    assert suffix.status_code == 206 and suffix.content == pdf_path.read_bytes()[-8:]
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{document.byte_size}"
    assert cors.status_code == 200
    assert "HEAD" in cors.headers["access-control-allow-methods"]


def test_verified_cdn_redirect_only_after_metadata_check(tmp_path: Path):
    registry, _pdf_path, document_id = _fixture_registry(tmp_path)
    storage = Mock()
    storage.url.return_value = "https://cdn.example/statutes/document.pdf"
    with patch("api.receipts.get_receipt_registry", return_value=registry), patch(
        "api.receipts.validate_available", return_value=("redirect", storage)
    ):
        response = TestClient(app).get(
            f"/receipts/{document_id}/pdf", follow_redirects=False
        )

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example/statutes/document.pdf"
    storage.url.assert_called_once_with(registry.get(document_id))


def test_cdn_sidecar_is_verified_by_metadata_and_download_hash():
    registry = ReceiptRegistry(DEFAULT_MANIFEST_PATH)
    document = registry.for_act("56")
    assert document is not None
    run = registry.active_extraction(document)
    assert run is not None and run.coordinate_sidecar is not None
    payload = registry.sidecar_path(run).read_bytes()
    head = Mock(
        headers={
            "Content-Length": str(len(payload)),
            "X-Corpus-SHA256": run.coordinate_sidecar.sha256,
            "Content-Type": "application/gzip",
            "ETag": '"sidecar"',
        }
    )
    head.raise_for_status.return_value = None
    download = Mock(content=payload)
    download.raise_for_status.return_value = None
    storage = CdnCorpusStorage("https://cdn.example")

    with patch("corpus.storage.requests.head", return_value=head), patch(
        "corpus.storage.requests.get", return_value=download
    ):
        metadata = storage.verify_sidecar(run)
        received = storage.get_sidecar(run)

    assert metadata.sha256 == run.coordinate_sidecar.sha256
    assert received == payload


def test_cdn_deep_verification_streams_and_hashes_exact_pdf(tmp_path: Path):
    registry, pdf_path, document_id = _fixture_registry(tmp_path)
    document = registry.get(document_id)
    response = Mock()
    response.raise_for_status.return_value = None
    response.iter_content.return_value = [pdf_path.read_bytes()[:13], pdf_path.read_bytes()[13:]]
    storage = CdnCorpusStorage("https://cdn.example")

    with patch("corpus.storage.requests.get", return_value=response):
        storage.deep_verify(document)

    response.close.assert_called_once()


def test_corrupt_document_endpoint_never_serves_bytes(tmp_path: Path):
    registry, pdf_path, document_id = _fixture_registry(tmp_path)
    pdf_path.write_bytes(pdf_path.read_bytes() + b"corrupt")
    with patch("api.receipts.get_receipt_registry", return_value=registry):
        response = TestClient(app).get(f"/receipts/{document_id}/pdf")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")


def test_locate_endpoint_contract_and_start_page_validation(tmp_path: Path):
    registry, _pdf_path, document_id = _fixture_registry(tmp_path)
    with patch("api.receipts.get_receipt_registry", return_value=registry):
        client = TestClient(app)
        matched = client.post(
            f"/receipts/{document_id}/locate",
            json={"evidence_quote": "Alpha evidence", "start_page": 1},
        )
        invalid = client.post(
            f"/receipts/{document_id}/locate",
            json={"evidence_quote": None, "start_page": 3},
        )

    assert matched.status_code == 200
    assert matched.json()["status"] == "matched"
    assert matched.json()["document"]["document_id"] == document_id
    assert invalid.status_code == 422


def test_unknown_document_never_reaches_validation():
    registry = Mock()
    registry.get.side_effect = ReceiptDocumentNotFound("unknown")
    with patch("api.receipts.get_receipt_registry", return_value=registry):
        response = TestClient(app).get("/receipts/unknown/pdf")

    assert response.status_code == 404
    registry.validate.assert_not_called()
