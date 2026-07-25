import hashlib
import json
from pathlib import Path

import fitz
import pytest

from citation_receipts.locator import locate_evidence
from corpus.extraction import extract_document, extract_manifest
from corpus.identity import asset_key, document_id, sha256_file
from corpus.manifest import generate_manifest
from corpus.models import CorpusDocument
from corpus.registry import CorpusDocumentIntegrityError, CorpusRegistry
from corpus.validation import validate_manifest


def _pdf(path: Path, lines: list[str] | None = None) -> None:
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    for index, line in enumerate(lines or []):
        page.insert_text((40, 60 + index * 20), line)
    document.save(path)
    document.close()


def _metadata(path: Path, act: str, source: str, *, detail: str = "lang=BI") -> None:
    path.write_text(json.dumps({
        "act_number": act,
        "scraped_at": "2026-01-02T00:00:00+00:00",
        "detail_url": f"https://example.test/{act}?{detail}",
        "latest_reprint_pdf": source,
        "timeline": [{"date": "01/01/2026", "log_type": "REPRINT ONLINE", "pdf_url": source}],
    }), encoding="utf-8")


def test_manifest_generation_is_deterministic_and_keeps_bm_sources(tmp_path: Path):
    pdf_root = tmp_path / "pdfs"
    metadata_root = tmp_path / "metadata"
    chunks_root = tmp_path / "chunks"
    for root in (pdf_root / "en", metadata_root, chunks_root):
        root.mkdir(parents=True)
    _pdf(pdf_root / "en" / "1.pdf", ["Short title", "1. This is enough legal section text to be extracted and registered as a fixture section."])
    _pdf(pdf_root / "en" / "144.pdf", ["Tajuk ringkas", "1. Ini ialah kandungan seksyen Bahasa Malaysia yang cukup panjang untuk ujian pendaftaran sumber."])
    _pdf(pdf_root / "en" / "2.pdf", ["1. Amendment only fixture text"])
    _metadata(metadata_root / "1.json", "1", "https://example.test/EN/Act-1.pdf")
    _metadata(metadata_root / "144.json", "144", "https://example.test/LOM/MY/Akta-144.pdf", detail="lang=BM")
    (metadata_root / "2.json").write_text(json.dumps({
        "act_number": "2", "detail_url": "https://example.test/2", "latest_reprint_pdf": "",
        "latest_amendment_pdf": "https://example.test/Act-A2.pdf",
    }), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"acts": [
        {"act_number": "1", "title_en": "FIXTURE ACT", "title_bm": "AKTA CONTOH"},
        {"act_number": "144", "title_en": "PETROLEUM ACT", "title_bm": "AKTA KEMAJUAN PETROLEUM"},
    ]}), encoding="utf-8")
    for act in ("1", "144"):
        (chunks_root / f"{act}.json").write_text(json.dumps([{"act_number": act}]), encoding="utf-8")

    first_manifest, first_report = generate_manifest(
        pdf_root=pdf_root, metadata_root=metadata_root, index_path=index, chunks_root=chunks_root
    )
    second_manifest, second_report = generate_manifest(
        pdf_root=pdf_root, metadata_root=metadata_root, index_path=index, chunks_root=chunks_root
    )

    assert first_manifest == second_manifest
    assert first_report == second_report
    assert len(first_manifest["documents"]) == 2
    assert len(first_manifest["source_observations"]) == 2
    bm = next(item for item in first_manifest["documents"] if item["act_number"] == "144")
    assert bm["language"] == "bm"
    assert bm["act_title"] == "AKTA KEMAJUAN PETROLEUM"
    amendment = next(item for item in first_report["pdfs"] if item["act_number"] == "2")
    assert amendment["reason"] == "amendment_only"
    assert amendment["requires_redownload"] and amendment["requires_reextraction"]

    previous_path = tmp_path / "previous-manifest.json"
    previous_path.write_text(json.dumps(first_manifest), encoding="utf-8")
    _pdf(pdf_root / "en" / "1.pdf", [
        "Replacement title",
        "1. Replacement legal section text is long enough to create a changed immutable document identity.",
    ])
    replaced_manifest, _ = generate_manifest(
        pdf_root=pdf_root, metadata_root=metadata_root, index_path=index,
        chunks_root=chunks_root, existing_manifest=previous_path,
    )
    versions = [item for item in replaced_manifest["documents"] if item["act_number"] == "1"]
    assert len(versions) == 2
    assert len({item["document_id"] for item in versions}) == 2
    assert {item["lifecycle_status"] for item in versions} == {"registered", "superseded"}


def test_registry_supports_versions_languages_aliases_and_history(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    paths = []
    for name, text in (("old.pdf", "old bytes"), ("new.pdf", "new bytes"), ("bm.pdf", "bm bytes")):
        path = assets / name
        _pdf(path, [text])
        paths.append(path)
    documents = []
    for path, language in ((paths[0], "en"), (paths[1], "en"), (paths[2], "bm")):
        digest = sha256_file(path)
        documents.append({
            "document_id": document_id("9", language, digest), "act_number": "9",
            "act_title": "ACT 9" if language == "en" else "AKTA 9", "language": language,
            "asset_key": asset_key(digest), "sha256": digest, "byte_size": path.stat().st_size,
            "page_count": 1, "source_url": "https://example.test/9.pdf", "timeline_date": "",
            "timeline_type": "REPRINT", "metadata_scraped_at": "2026-01-01T00:00:00Z",
            "lifecycle_status": "registered", "document_kind": "reprint", "detail_url": "",
            "local_path": path.name,
        })
    manifest = {"schema_version": 2, "identity_algorithm": "sha256", "documents": documents,
                "extraction_runs": [], "active_documents": [], "aliases": {"saved-old": documents[0]["document_id"]}}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=assets)

    assert registry.get("saved-old").document_id == documents[0]["document_id"]
    assert len(registry.versions_for_act("9", "en")) == 2
    assert len(registry.versions_for_act("9")) == 3
    assert registry.for_act("9", "en") is None
    registry.validate(registry.get(documents[1]["document_id"]))
    paths[1].write_bytes(paths[1].read_bytes() + b"corrupt")
    with pytest.raises(CorpusDocumentIntegrityError):
        registry.validate(registry.get(documents[1]["document_id"]))


def test_exact_extraction_sidecar_locator_and_scanned_failure(tmp_path: Path):
    asset_root = tmp_path / "assets"
    sidecar_root = tmp_path / "sidecars"
    extraction_root = tmp_path / "extractions"
    asset_root.mkdir()
    pdf_path = asset_root / "fixture.pdf"
    _pdf(pdf_path, [
        "Short title",
        "1. Alpha evidence appears here and this section contains",
        "enough additional legal fixture words to pass extraction.",
        "The remaining sentence makes the text-layer threshold unambiguous.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("99", "en", digest), "99", "FIXTURE ACT", "en", asset_key(digest), digest,
        pdf_path.stat().st_size, 1, "https://example.test/99.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {},
        "source_observations": [{
            "document_id": document.document_id,
            "source_url": document.source_url,
            "observed_at": document.metadata_scraped_at,
        }],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)
    run, _bundle = extract_document(
        registry, document, extraction_root=extraction_root, sidecar_root=sidecar_root
    )
    sidecar_path = sidecar_root / run.coordinate_sidecar.local_path
    located = locate_evidence(
        pdf_path, "Alpha evidence appears here", 1, sidecar_path=sidecar_path,
        document_id=document.document_id, document_sha256=document.sha256,
    )
    assert located.status == "matched" and located.pages[0].rectangles

    updated_manifest, _report = extract_manifest(
        registry,
        extraction_root=extraction_root,
        sidecar_root=sidecar_root,
        document_ids=[document.document_id],
    )
    assert updated_manifest["source_observations"] == registry.source_observations

    scanned_path = asset_root / "scanned.pdf"
    _pdf(scanned_path, [])
    scanned_digest = sha256_file(scanned_path)
    scanned = CorpusDocument(
        document_id("100", "en", scanned_digest), "100", "SCANNED", "en", asset_key(scanned_digest),
        scanned_digest, scanned_path.stat().st_size, 1, "https://example.test/100.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=scanned_path.name,
    )
    scanned_manifest = tmp_path / "scanned-manifest.json"
    scanned_manifest.write_text(json.dumps({
        "schema_version": 2, "documents": [scanned.to_dict()], "extraction_runs": [],
        "active_documents": [], "aliases": {},
    }), encoding="utf-8")
    scanned_registry = CorpusRegistry(scanned_manifest, asset_root=asset_root)
    with pytest.raises(ValueError, match="scanned_image_only"):
        extract_document(scanned_registry, scanned, extraction_root=extraction_root, sidecar_root=sidecar_root)


def test_checked_in_coverage_accounts_for_every_source_pdf():
    root = Path(__file__).resolve().parents[1]
    coverage = json.loads((root / "data" / "corpus" / "coverage.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "data" / "pdfs" / "manifest.json").read_text(encoding="utf-8"))

    assert coverage["input_pdf_count"] == 624
    assert len(coverage["pdfs"]) == 624
    assert len({item["pdf"] for item in coverage["pdfs"]}) == 624
    assert coverage["enabled_pdf_count"] == 5
    assert coverage["ready_pdf_count"] == 571
    assert coverage["blocked_pdf_count"] == 48
    assert coverage["reason_counts"]["amendment_only"] == 28
    assert len(manifest["documents"]) == 601
    september = next(
        item for item in manifest["documents"]
        if item["document_id"]
        == "act-265-en-sha256-6ef0ba72dc9c149c474d7989b8c3b39168c753472d11a64d720bd227e12a3bf7"
    )
    assert september["timeline_date"] == "02/09/2023"
    assert september["timeline_type"] == "REPRINT"
    assert {
        item["timeline_date"]
        for item in manifest["documents"]
        if item["act_number"] == "265"
    } == {
        "10/01/1975", "20/08/2001", "24/01/2006",
        "26/05/2012", "01/02/2023", "02/09/2023",
    }
    assert len(manifest["extraction_runs"]) == 576
    assert {item["act_number"] for item in manifest["documents"] if item["language"] == "bm"} == {
        "144", "152", "194", "220", "228", "230",
    }
