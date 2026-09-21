import hashlib
import json
from pathlib import Path

import fitz
import pytest

from citation_receipts.locator import locate_evidence
from corpus.extraction import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    SCANNED_THRESHOLD,
    _DIVISION_RE,
    _ENACTING_FORMULA_RE,
    _chunk_quality,
    _extraction_accounting,
    _is_heading_case,
    _is_scanned,
    _page_span_bucket,
    chunk_looks_like_table_of_contents,
    diff_chunk_sets,
    diff_extraction_manifests,
    extract_document,
    extract_manifest,
)
from corpus.identity import asset_key, content_hash, document_id, extraction_id, sha256_file
from corpus.manifest import generate_manifest
from corpus.models import ActiveDocument, CoordinateSidecar, CorpusDocument, ExtractionRun
from corpus.registry import CorpusDocumentIntegrityError, CorpusRegistry
from corpus.validation import validate_manifest


def _pdf(path: Path, lines: list[str] | None = None) -> None:
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    for index, line in enumerate(lines or []):
        page.insert_text((40, 60 + index * 20), line)
    document.save(path)
    document.close()


def _divided_pdf(path: Path, pages: list[list[tuple[str, bool]]]) -> None:
    """Write a PDF whose lines are left-aligned unless the tuple asks for centring.

    The extractor tells a real division heading from the table-of-contents copy of
    it by how close to the page centre it sits, so the fixture has to place text,
    not just write it.
    """
    document = fitz.open()
    for lines in pages:
        page = document.new_page(width=400, height=500)
        for index, (line, centred) in enumerate(lines):
            left = (400 - fitz.get_text_length(line, fontsize=11)) / 2 if centred else 40
            page.insert_text((left, 60 + index * 20), line, fontsize=11)
    document.save(path)
    document.close()


def _scanned_pdf(path: Path, lines: list[str], *, dpi: int = 150) -> None:
    """An image-only PDF: the same text `_pdf` would write, rendered to a pixmap and
    embedded as an image with no text layer, so `_is_scanned` sees it as scanned and
    only OCR can recover its content. The page is sized from the pixmap's own
    resolution so it matches what a real scan's page geometry looks like.
    """
    source = fitz.open()
    page = source.new_page(width=400, height=500)
    for index, line in enumerate(lines):
        page.insert_text((40, 60 + index * 20), line, fontsize=11)
    pixmap = page.get_pixmap(dpi=dpi)
    source.close()
    image = fitz.open()
    image_page = image.new_page(width=pixmap.width * 72 / dpi, height=pixmap.height * 72 / dpi)
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    image.save(path)
    image.close()


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


def test_manifest_and_extraction_share_one_scanned_check():
    from corpus.manifest import _is_scanned as manifest_is_scanned

    assert manifest_is_scanned is _is_scanned


def test_is_scanned_at_the_threshold_boundary(tmp_path: Path):
    # Single-page fixtures with an exact, empirically-verified character count
    # (10 lines of 9 chars + 9 lines of 10 chars, each insert_text call
    # contributing width+1 for its trailing newline): one lands exactly on
    # SCANNED_THRESHOLD, the other one character under it.
    at_threshold = tmp_path / "at-threshold.pdf"
    _pdf(at_threshold, ["x" * 9] * 10)
    below_threshold = tmp_path / "below-threshold.pdf"
    _pdf(below_threshold, ["x" * 10] * 9)

    with fitz.open(at_threshold) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == SCANNED_THRESHOLD
        assert _is_scanned(pdf) is False
    with fitz.open(below_threshold) as pdf:
        assert sum(len(page.get_text()) for page in pdf) == SCANNED_THRESHOLD - 1
        assert _is_scanned(pdf) is True


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
    # A genuinely blank scanned page still fails: OCR runs (ADR 0019) but
    # finds nothing to extract, so this ends in no_chunks.
    with pytest.raises(ValueError, match="no_chunks"):
        extract_document(scanned_registry, scanned, extraction_root=extraction_root, sidecar_root=sidecar_root)


def test_scanned_document_is_recovered_through_ocr_deterministically(tmp_path: Path):
    asset_root = tmp_path / "assets"
    sidecar_root = tmp_path / "sidecars"
    extraction_root = tmp_path / "extractions"
    asset_root.mkdir()
    pdf_path = asset_root / "scanned-fixture.pdf"
    _scanned_pdf(pdf_path, [
        "Short title",
        "1. Alpha evidence appears here and this section contains",
        "enough additional legal fixture words to pass extraction.",
        "The remaining sentence makes the text-layer threshold unambiguous.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("101", "en", digest), "101", "SCANNED FIXTURE ACT", "en", asset_key(digest), digest,
        pdf_path.stat().st_size, 1, "https://example.test/101.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {},
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)

    assert _is_scanned(fitz.open(pdf_path)) is True

    first_run, _bundle = extract_document(
        registry, document, extraction_root=extraction_root, sidecar_root=sidecar_root
    )
    assert first_run.chunk_count >= 1
    sidecar_path = sidecar_root / first_run.coordinate_sidecar.local_path
    located = locate_evidence(
        pdf_path, "Alpha evidence appears here", 1, sidecar_path=sidecar_path,
        document_id=document.document_id, document_sha256=document.sha256,
    )
    assert located.status == "matched" and located.pages[0].rectangles

    # Extracting the same scanned document again must reproduce the identical
    # chunk_set_hash and sidecar SHA-256 (#104's determinism acceptance
    # criterion) -- registry.extraction_runs already holds the first run, so a
    # second call that disagrees raises extraction_identity_drift instead of
    # silently overwriting it.
    registry.extraction_runs[first_run.extraction_id] = first_run
    second_run, _bundle = extract_document(
        registry, document, extraction_root=extraction_root, sidecar_root=sidecar_root
    )
    assert second_run.chunk_set_hash == first_run.chunk_set_hash
    assert second_run.coordinate_sidecar.sha256 == first_run.coordinate_sidecar.sha256


def test_ocr_config_changes_the_configuration_hash():
    from corpus.extraction import CONFIGURATION_HASH, EXTRACTOR_CONFIG
    from corpus.identity import sha256_json

    for key in ("ocr_render_dpi", "ocr_language_by_document_language", "ocr_engine"):
        assert key in EXTRACTOR_CONFIG
    changed = sha256_json({**EXTRACTOR_CONFIG, "ocr_render_dpi": 150})
    assert changed != CONFIGURATION_HASH


def test_extract_manifest_skips_accounting_for_scanned_documents(tmp_path: Path):
    asset_root = tmp_path / "assets"
    sidecar_root = tmp_path / "sidecars"
    extraction_root = tmp_path / "extractions"
    asset_root.mkdir()

    text_path = asset_root / "text.pdf"
    _pdf(text_path, [
        "Short title",
        "1. Alpha evidence appears here and this section contains",
        "enough additional legal fixture words to pass extraction.",
    ])
    scanned_path = asset_root / "scanned.pdf"
    _scanned_pdf(scanned_path, [
        "Short title",
        "1. Alpha evidence appears here and this section contains",
        "enough additional legal fixture words to pass extraction.",
    ])
    text_digest = sha256_file(text_path)
    scanned_digest = sha256_file(scanned_path)
    text_document = CorpusDocument(
        document_id("102", "en", text_digest), "102", "TEXT ACT", "en", asset_key(text_digest),
        text_digest, text_path.stat().st_size, 1, "https://example.test/102.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=text_path.name,
    )
    scanned_document = CorpusDocument(
        document_id("103", "en", scanned_digest), "103", "SCANNED ACT", "en", asset_key(scanned_digest),
        scanned_digest, scanned_path.stat().st_size, 1, "https://example.test/103.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=scanned_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256",
        "documents": [text_document.to_dict(), scanned_document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {},
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)

    _manifest, report = extract_manifest(
        registry, extraction_root=extraction_root, sidecar_root=sidecar_root,
        document_ids=[text_document.document_id, scanned_document.document_id],
    )
    results = {item["document_id"]: item for item in report["documents"]}
    text_result = results[text_document.document_id]
    scanned_result = results[scanned_document.document_id]

    assert text_result["ocr"] is False
    assert text_result["pdf_chars"] > 0
    assert scanned_result["ocr"] is True
    assert scanned_result["pdf_chars"] == 0
    assert scanned_result["assigned_chars"] == 0
    assert scanned_result["classified_chars"] == 0
    assert scanned_result["unassigned_chars"] == 0


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
    # Far more documents than coverage inputs. coverage.json is written by
    # `corpus generate-manifest`, which has not been re-run since the 2026-09-13
    # bilingual sweep registered 485 more documents (475 of them Malay) on top of
    # the 38 Acts the step 3 timeout fix recovered earlier. The counts above
    # describe the corpus as coverage last saw it; this one describes it now.
    assert len(manifest["documents"]) == 1124
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
    assert len(manifest["extraction_runs"]) == 1079
    bm_acts = {item["act_number"] for item in manifest["documents"] if item["language"] == "bm"}
    assert len(bm_acts) == 481
    # The six BM-only Acts registered before the bilingual sweep. Pinning all 481
    # would restate the fixture; this checks none of the original six was dropped.
    assert {"144", "152", "194", "220", "228", "230"} <= bm_acts


# #74: the corpus-wide retention `data/chunks/extract_report.json` measured
# when per-document character accounting first landed (assigned_chars /
# pdf_chars over all ready documents). A drop below this means an extraction
# change is silently losing more text than it used to keep — investigate
# before merging, don't just lower the number.
RECORDED_RETENTION_BASELINE = 0.9234


def test_corpus_wide_retention_has_not_regressed_below_its_recorded_baseline():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "data" / "chunks" / "extract_report.json").read_text(encoding="utf-8"))
    totals = report["totals"]
    retention = totals["assigned_chars"] / totals["pdf_chars"]
    assert retention >= RECORDED_RETENTION_BASELINE, (
        f"corpus-wide retention {retention:.4f} fell below the recorded baseline {RECORDED_RETENTION_BASELINE}"
    )


# #92: a `ready` document that is almost entirely one unnumbered blob chunk (#89)
# reports success while holding almost nothing retrievable — Act 12 EN's only
# chunk is its list of amendments, 1.3% of the document. Ceiling, not a target: it
# must not grow silently.
RECORDED_LOW_YIELD_CEILING = 37


def test_low_yield_ready_documents_have_not_grown_past_their_recorded_ceiling():
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "data" / "chunks" / "extract_report.json").read_text(encoding="utf-8"))
    low_yield = [
        item for item in report["documents"]
        if item["status"] == "ready"
        and (item["chunk_count"] <= 2 or item["assigned_chars"] / item["pdf_chars"] < 0.5)
    ]
    low_yield_ids = {item["document_id"] for item in low_yield}
    assert len(low_yield) <= RECORDED_LOW_YIELD_CEILING, (
        f"{len(low_yield)} ready documents are low-yield (<=2 chunks or <50% assigned), "
        f"above the recorded ceiling of {RECORDED_LOW_YIELD_CEILING}: {sorted(low_yield_ids)}"
    )
    # Names a known #72-cohort failure so the guard is provably firing, not just
    # counting: Act 33 EN has no detectable enacting formula, so #94's
    # bare-line pattern stays off for it and its whole chunk set is still one
    # 6.3%-of-the-document blob.
    assert "act-33-en-sha256-7f62b6ce790ee848b027d357a1f25e20975c81c98ed17f53554c46ff20bcd459" in low_yield_ids


def _single_active_document_manifest(tmp_path: Path, *, extractor_version: str) -> Path:
    digest = "d" * 64
    doc_id = document_id("1", "en", digest)
    document = CorpusDocument(
        doc_id, "1", "FIXTURE ACT", "en", asset_key(digest), digest, 100, 1,
        "https://example.test/1.pdf", "", "REPRINT", "2026-01-01T00:00:00Z", local_path="1.pdf",
    )
    config_hash = "a" * 64
    ext_id = extraction_id(doc_id, EXTRACTOR, extractor_version, config_hash)
    sidecar_sha = "b" * 64
    run = ExtractionRun(
        extraction_id=ext_id, document_id=doc_id, extractor=EXTRACTOR,
        extractor_version=extractor_version, configuration_hash=config_hash,
        chunk_set_hash="c" * 64, chunk_count=1, status="ready",
        coordinate_sidecar=CoordinateSidecar(
            asset_key=f"statutes/extractions/{ext_id}/{sidecar_sha}.words.json.gz",
            sha256=sidecar_sha, byte_size=10, local_path=f"{ext_id}.words.json.gz",
        ),
    )
    active = ActiveDocument("1", "en", doc_id, ext_id)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256",
        "documents": [document.to_dict()], "extraction_runs": [run.to_dict()],
        "active_documents": [active.to_dict()], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    return manifest_path


def test_validate_manifest_warns_when_active_extractor_version_is_behind_main(tmp_path: Path):
    """#89: an active extraction run built under an older EXTRACTOR_VERSION than
    the one corpus/extraction.py computes today must surface as a warning, not
    silence. `valid` stays true -- drift is expected mid-rollout -- but it must
    not be invisible."""
    manifest_path = _single_active_document_manifest(tmp_path, extractor_version="1.0.0")
    result = validate_manifest(manifest_path, scope="registry")
    assert result["valid"]
    codes = {warning["code"] for warning in result["warnings"]}
    assert "extractor_version_drift" in codes


def test_validate_manifest_does_not_warn_when_active_extractor_version_matches_main(tmp_path: Path):
    manifest_path = _single_active_document_manifest(tmp_path, extractor_version=EXTRACTOR_VERSION)
    result = validate_manifest(manifest_path, scope="registry")
    assert result["warnings"] == []


def test_manifest_active_extractor_version_drift_is_visible_not_silent():
    """#89: the real manifest's active extraction_runs fell behind EXTRACTOR_VERSION
    for five version bumps (2.1.0 through 2.5.0) before anyone noticed, because
    nothing surfaced the gap short of manually running extract_manifest and
    diffing by hand. This pins today's real gap so it stays a conscious, visible
    fact. Once #89's activation actually happens, this test starts failing --
    fix it by asserting the warning is gone (and update/close #89), not by
    deleting the check, so the next drift gets caught the same way."""
    root = Path(__file__).resolve().parents[1]
    result = validate_manifest(root / "data" / "pdfs" / "manifest.json", scope="registry")
    codes = {warning["code"] for warning in result["warnings"]}
    assert "extractor_version_drift" in codes, (
        f"expected the manifest's active extraction_runs to still be behind "
        f"EXTRACTOR_VERSION ({EXTRACTOR_VERSION}) -- if #89 activated for real, "
        "update this test rather than deleting the check"
    )


def test_scraped_at_for_files_each_language_under_its_own_scrape_date():
    """A Malay document backfilled onto an Act scraped months earlier must not
    inherit the English scrape's date (#71)."""
    from corpus.manifest import scraped_at_for

    metadata = {
        "scraped_at": "2026-05-07T02:28:40+00:00",
        "scraped_at_bm": "2026-09-13T00:53:29+00:00",
    }

    assert scraped_at_for(metadata, "bm") == "2026-09-13T00:53:29+00:00"
    assert scraped_at_for(metadata, "en") == "2026-05-07T02:28:40+00:00"


def test_scraped_at_for_falls_back_to_the_act_level_stamp():
    """Metadata written before the per-language stamp existed carries only
    scraped_at, and that is the right answer for the primary document."""
    from corpus.manifest import scraped_at_for

    metadata = {"scraped_at": "2026-05-07T02:28:40+00:00"}

    assert scraped_at_for(metadata, "bm") == "2026-05-07T02:28:40+00:00"
    assert scraped_at_for(metadata, "en") == "2026-05-07T02:28:40+00:00"
    assert scraped_at_for({}, "bm") == ""


def _signed(inner: str) -> str:
    """A processFile.php link of the shape AGC serves since issue #64."""
    import base64

    token = base64.b64encode(f"{inner}|{'a' * 64}".encode("utf-8")).decode("ascii")
    return f"https://lom.agc.gov.my/processFile.php?isDirect=1&token={token}"


def test_source_language_reads_the_language_out_of_a_signed_detail_link():
    """Since #64 detail_url carries no plain lang= marker, so the pre-#64 check
    matches nothing and every re-scraped Malay Act would fall through to "en"
    unless the token is decoded."""
    from corpus.manifest import source_language

    metadata = {"detail_url": _signed("https://lom.agc.gov.my/act-detail.php?act=144&lang=BM&date=01-01-2020")}
    # A Malay reprint whose PDF path carries no /MY/ or _bm/ marker — 19 of
    # these are in the corpus, so the URL alone cannot classify them.
    unmarked = "https://lom.agc.gov.my/ilims/upload/portal/akta/outputaktap/Akta 580.pdf"

    assert source_language(metadata, unmarked) == "bm"


def test_source_language_reads_english_out_of_a_signed_detail_link():
    from corpus.manifest import source_language

    metadata = {"detail_url": _signed("https://lom.agc.gov.my/act-detail.php?act=100&lang=BI&date=01-01-2020")}

    assert source_language(metadata, "https://lom.agc.gov.my/ilims/upload/portal/akta/outputaktap/Act 100.pdf") == "en"


def test_source_language_still_reads_the_pre_64_url_markers():
    """Metadata already on disk carries plain act-detail.php URLs, and its
    documents must keep the language they were registered under."""
    from corpus.manifest import source_language

    legacy = {"detail_url": "https://lom.agc.gov.my/act-detail.php?act=144&lang=BM"}
    assert source_language(legacy, "https://lom.agc.gov.my/x/Akta 144.pdf") == "bm"
    assert source_language({}, "https://lom.agc.gov.my/ilims/upload/portal/akta/LOM/MY/Akta 152.pdf") == "bm"
    assert source_language({}, "https://lom.agc.gov.my/ilims/upload/portal/akta/LOM/Act 152.pdf") == "en"


def test_source_language_ignores_an_undecodable_token():
    """A token that is not base64, or carries no lang marker, must fall through
    to the URL markers rather than throwing."""
    from corpus.manifest import source_language

    assert source_language({"detail_url": "https://lom.agc.gov.my/processFile.php?token=!!!"}, "") == "en"
    assert source_language(
        {"detail_url": _signed("https://lom.agc.gov.my/act-detail.php?act=1")},
        "https://lom.agc.gov.my/ilims/upload/portal/akta/LOM/MY/Akta 1.pdf",
    ) == "bm"


@pytest.mark.parametrize("heading", [
    "FIRST SCHEDULE", "THIRTEENTH SCHEDULE", "SCHEDULE", "SCHEDULE 4A", "SCHEDULE A",
    "Schedule", "JADUAL", "JADUAL PERTAMA", "Jadual Kedua", "LIST OF AMENDMENTS",
    "LISTS OF AMENDMENTS", "SENARAI PINDAAN",
])
def test_division_headings_recognised(heading: str):
    assert _DIVISION_RE.match(heading.upper())


@pytest.mark.parametrize("line", [
    "SCHEDULE OF FEES", "ARRANGEMENT OF SECTIONS", "PART I", "LAWS OF MALAYSIA",
    # A long all-caps line: the pattern has to reject this quickly rather than
    # backtrack over it, because every centred line of every page is tested.
    "SET OUT IN THE SCHEDULE TO THIS ACT AND NOT ELSEWHERE",
])
def test_lines_that_are_not_division_headings(line: str):
    assert not _DIVISION_RE.match(line.upper())


@pytest.mark.parametrize("line", [
    "in the First Schedule", "as specified in the First Schedule.",
    "of First Schedule) Order",
])
def test_prose_mentioning_a_schedule_is_not_heading_case(line: str):
    # The pattern matches these once uppercased; the case rule is what rejects them.
    assert not _is_heading_case(line)


def test_schedule_paragraph_does_not_overwrite_the_body_section_it_collides_with(tmp_path: Path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "divided.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Divided Fixture Act 2026 and comes", False),
            ("into operation on a date the Minister appoints by notification.", False),
            ("2. In this Act, unless the context otherwise requires, the words below", False),
            ("carry the meanings given to them in this section of the fixture.", False),
        ],
        [
            ("FIRST SCHEDULE", True),
            ("1. The liquidator may, with the authority of the Court, carry on the", False),
            ("business of the company so far as is necessary for winding it up.", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("98", "en", digest), "98", "DIVIDED FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/98.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert ("body", "s.1") in by_key and ("FIRST SCHEDULE", "sched.1/para.1") in by_key
    assert "may be cited as" in by_key[("body", "s.1")]["content"]
    assert "liquidator" in by_key[("FIRST SCHEDULE", "sched.1/para.1")]["content"]
    assert by_key[("body", "s.2")]["division"] == "body"
    # The heading is a boundary, not content: it belongs to neither paragraph.
    assert "FIRST SCHEDULE" not in by_key[("body", "s.2")]["content"]
    # #95: a schedule paragraph's own number lives in `path`, not `section_number`
    # - that's what stops it colliding with the body section sharing its number.
    assert by_key[("FIRST SCHEDULE", "sched.1/para.1")]["section_number"] == ""


def test_table_of_contents_copy_of_a_heading_is_not_a_division_boundary(tmp_path: Path):
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "contents.pdf"
    _divided_pdf(pdf_path, [
        [("ARRANGEMENT OF SECTIONS", True), ("FIRST SCHEDULE", True)],
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Contents Fixture Act 2026 and comes", False),
            ("into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("FIRST SCHEDULE", True),
            ("1. The liquidator may, with the authority of the Court, carry on the", False),
            ("business of the company so far as is necessary for winding it up.", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("97", "en", digest), "97", "CONTENTS FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 3, "https://example.test/97.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    # The copy on page 1 is the table of contents; the division starts on page 3.
    assert by_key[("body", "s.1")]["page_start"] == 2
    assert by_key[("FIRST SCHEDULE", "sched.1/para.1")]["page_start"] == 3


def test_division_content_without_numbered_paragraphs_is_kept_not_dropped(tmp_path: Path):
    """#89: a division heading reset `current_num` to `None`, which only a line
    matching `SECTION_PATTERN` ever set again — so a schedule whose own text
    never restarts at "1." lost every line between its heading and the next
    boundary. Act 485's Seventh Schedule reprints the UN Convention on
    Privileges and Immunities, numbered "Article I", "Article II" — roman,
    not arabic, and title case rather than upper. #94 gives a schedule its
    own item scheme, but only for the tokens `_SECTION_RE`'s grammar can
    represent (1-3 digits, optionally lettered); a roman-numeral instrument
    like this one has no token to take, so it must still come through whole
    rather than dropped or half-matched on "I"/"II" as if they were letters."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "prose_schedule.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Prose Schedule Fixture Act 2026 and", False),
            ("comes into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("SECOND SCHEDULE", True),
            ("Article I", False),
            ("The High Contracting Parties undertake to respect and to ensure", False),
            ("respect for the present Convention in all circumstances without any", False),
            ("adverse distinction founded on sex, race, nationality or religion.", False),
            ("Article II", False),
            ("In addition to the provisions implemented in peace time, the present", False),
            ("Convention shall apply to all cases of declared war or of any other", False),
            ("armed conflict arising between two or more of the High Contracting", False),
            ("Parties, even if the state of war is not recognised by one of them.", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("95", "en", digest), "95", "PROSE SCHEDULE FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/95.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key
    assert ("SECOND SCHEDULE", "") in by_key
    schedule_content = by_key[("SECOND SCHEDULE", "")]["content"]
    assert "High Contracting Parties" in schedule_content
    assert "Article II" in schedule_content
    assert "declared war" in schedule_content

    with fitz.open(pdf_path) as pdf:
        accounting = _extraction_accounting(pdf, document)
    assert accounting.pdf_chars == (
        accounting.assigned_chars + accounting.classified_chars + accounting.unassigned_chars
    )
    assert accounting.assigned_chars >= len(schedule_content)
    # Only the heading line itself is never content; nothing else under it
    # should still be falling through to unassigned.
    assert accounting.unassigned_chars < len("SECOND SCHEDULE") + 40


def test_schedule_article_number_becomes_its_own_chunk(tmp_path: Path):
    """#94: Act 512's Second Schedule reprints the Geneva Convention, numbered
    "ARTICLE 1", "ARTICLE 2" - upper case, arabic. Unlike the roman-numeral
    instrument above, this token fits `_SECTION_RE`'s grammar, so each
    article becomes its own addressable chunk instead of one blob covering
    the whole schedule."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "article_schedule.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Article Schedule Fixture Act 2026 and", False),
            ("comes into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("SECOND SCHEDULE", True),
            ("ARTICLE 1", False),
            ("The High Contracting Parties undertake to respect and to ensure", False),
            ("respect for the present Convention in all circumstances without any", False),
            ("adverse distinction founded on sex, race, nationality or religion.", False),
            ("ARTICLE 2", False),
            ("In addition to the provisions implemented in peace time, the present", False),
            ("Convention shall apply to all cases of declared war or of any other", False),
            ("armed conflict arising between two or more of the High Contracting", False),
            ("Parties, even if the state of war is not recognised by one of them.", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("99", "en", digest), "99", "ARTICLE SCHEDULE FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/99.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert ("SECOND SCHEDULE", "sched.1") not in by_key
    assert "respect for the present Convention" in by_key[("SECOND SCHEDULE", "sched.1/art.1")]["content"]
    assert "declared war" in by_key[("SECOND SCHEDULE", "sched.1/art.2")]["content"]
    # #95: two distinct schedule items get distinct, non-colliding paths, and
    # neither carries a `section_number` any more (that's `path`'s job now).
    assert by_key[("SECOND SCHEDULE", "sched.1/art.1")]["section_number"] == ""
    assert by_key[("SECOND SCHEDULE", "sched.1/art.2")]["section_number"] == ""

    with fitz.open(pdf_path) as pdf:
        accounting = _extraction_accounting(pdf, document)
    assert accounting.pdf_chars == (
        accounting.assigned_chars + accounting.classified_chars + accounting.unassigned_chars
    )


def test_article_cross_reference_wrapped_onto_its_own_line_is_not_a_new_article(tmp_path: Path):
    """#94: AGC's line wrap can split a running cross-reference like "as defined
    in Article 13." into "...in Article" / "13.", measured 3 times across the
    real Act 512. The real heading is upper case ("ARTICLE 13"); the wrapped
    reference is title case ("Article 13.") and must not be mistaken for one,
    or it would flush the article actually open and start a bogus one."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "article_reference.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Article Reference Fixture Act 2026 and", False),
            ("comes into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("SECOND SCHEDULE", True),
            ("ARTICLE 12", False),
            ("Nationals of a neutral State are wider in application, as defined in", False),
            ("Article 13.", False),
            ("Persons protected by the Convention are entitled to respect in all", False),
            ("circumstances for their persons, their honour and their family rights.", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("100", "en", digest), "100", "ARTICLE REFERENCE FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/100.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert ("SECOND SCHEDULE", "sched.1/art.13") not in by_key
    article_12 = by_key[("SECOND SCHEDULE", "sched.1/art.12")]["content"]
    assert "Article 13." in article_12
    assert "family rights" in article_12


def test_division_heading_with_nothing_under_it_produces_no_spurious_chunk(tmp_path: Path):
    """A division whose run has no real content before the next boundary or EOF
    must not emit an empty/near-empty chunk — MIN_CONTENT_CHARS has to keep
    working now that `current_num` starts at `""` under a heading rather than
    `None`."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "empty_schedule.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Empty Schedule Fixture Act 2026 and", False),
            ("comes into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("Interpretation", False),
            ("2. In this Act, unless the context otherwise requires, the words below", False),
            ("carry the meanings given to them in this section of the fixture text.", False),
        ],
        [("THIRD SCHEDULE", True)],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("94", "en", digest), "94", "EMPTY SCHEDULE FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 3, "https://example.test/94.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key
    assert ("body", "2") in by_key
    assert ("THIRD SCHEDULE", "") not in by_key
    assert len(chunks) == 2


def _fixture_document(
    tmp_path: Path, name: str, act_number: str, pages: list[list[tuple[str, bool]]]
) -> tuple[CorpusRegistry, CorpusDocument]:
    asset_root = tmp_path / "assets"
    asset_root.mkdir(exist_ok=True)
    pdf_path = asset_root / f"{name}.pdf"
    _divided_pdf(pdf_path, pages)
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id(act_number, "en", digest), act_number, f"{name.upper()} FIXTURE ACT", "en",
        asset_key(digest), digest, pdf_path.stat().st_size, len(pages),
        f"https://example.test/{act_number}.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / f"{name}-manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / f"{name}-sidecars")
    return registry, document


def test_body_section_split_across_a_bare_number_line_is_still_recognised(tmp_path: Path):
    """#72: 22 real documents print a section's number alone on its own line -
    its title on the line above, its text starting on the line after -
    which `SECTION_PATTERN`'s one-line "number, dot, text" shape never
    matches, so these Acts produced zero chunks. This is Act 12/22/66 EN's
    real layout. Needs a real enacting formula: the pattern only fires once
    front matter has a confirmed end (#93's guard, added after Act 595
    showed what happens without one)."""
    registry, document = _fixture_document(tmp_path, "split_heading", "101", [[
        ("BE IT ENACTED by the Parliament of Malaysia as follows:", False),
        ("Short title", False),
        ("1.", False),
        ("This Act may be cited as the Split Heading Fixture Act 2026.", False),
        ("Interpretation", False),
        ("2.", False),
        ("In this Act, unless the context otherwise requires, the words below", False),
        ("carry the meanings given to them in this section of the fixture.", False),
    ]])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert "Short title" in by_key[("body", "1")]["content"]
    assert "may be cited as" in by_key[("body", "1")]["content"]
    assert "context otherwise requires" in by_key[("body", "2")]["content"]


def test_bare_number_line_after_long_prose_does_not_split_the_section(tmp_path: Path):
    """The discriminator #72 needs is order, not shape: a bare number only
    starts a new section when the line above it reads as a title, not when
    it is a `(a)`-style continuation of the section's own prose. Otherwise a
    stray enumeration mark inside a section's own text would be split into
    a bogus new section."""
    registry, document = _fixture_document(tmp_path, "enumeration", "102", [[
        ("BE IT ENACTED by the Parliament of Malaysia as follows:", False),
        ("Short title", False),
        ("1.", False),
        ("This Act may be cited as the Enumeration Fixture Act 2026.", False),
        ("(a) matters relating to contributions payable under this Act; and", False),
        ("5.", False),
        ("the rate of contribution payable by an employer under this Act.", False),
    ]])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "5") not in by_key
    assert "the rate of contribution" in by_key[("body", "1")]["content"]


def test_schedule_paragraph_split_across_its_own_line_becomes_its_own_chunk(tmp_path: Path):
    """#94: some schedules number their own paragraphs the same split-line way
    the body's #72 cohort does - Act 4's Fifth Schedule prints "4." /
    "Barium" / the disease description, not "4. Barium ...". A schedule has
    no title line above each paragraph the way the body does, so this is
    recognised unconditionally rather than gated on the line above."""
    registry, document = _fixture_document(tmp_path, "schedule_item", "103", [
        [("Short title", False), ("1. This Act may be cited as the Schedule Item Fixture Act 2026.", False)],
        [
            ("FIRST SCHEDULE", True),
            ("Occupation", False),
            ("1.", False),
            ("Fitters and turners engaged wholly or mainly upon the maintenance or", False),
            ("repair of machinery.", False),
            ("2.", False),
            ("Persons who in the course of their employment are subject to excessive", False),
            ("heat or humidity or to rapid variations of temperature.", False),
        ],
    ])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert ("FIRST SCHEDULE", "sched.1") not in by_key
    assert "maintenance" in by_key[("FIRST SCHEDULE", "sched.1/para.1")]["content"]
    assert "excessive" in by_key[("FIRST SCHEDULE", "sched.1/para.2")]["content"]


def test_schedule_bare_item_after_a_reference_word_is_not_a_new_item(tmp_path: Path):
    """#94: a schedule's bare-dot numbering carries the same line-wrap risk as
    `ARTICLE n` - Act 148's Montreal Protocol schedule measured this exact
    shape: "...laid down in paragraph" / "1.". A schedule has no title line
    to gate a bare item the way the body does, so this checks whether the
    line above ends in a reference noun instead."""
    registry, document = _fixture_document(tmp_path, "reference_tail", "104", [
        [("Short title", False), ("1. This Act may be cited as the Reference Tail Fixture Act 2026.", False)],
        [
            ("FIRST SCHEDULE", True),
            ("2.", False),
            ("The rules in this Schedule are the ones laid down in paragraph", False),
            ("1.", False),
            ("of this Schedule and to no other carriage.", False),
        ],
    ])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert ("FIRST SCHEDULE", "sched.1/para.1") not in by_key
    assert "of this Schedule and to no other carriage" in by_key[("FIRST SCHEDULE", "sched.1/para.2")]["content"]


def test_list_of_amendments_never_produces_a_numbered_item(tmp_path: Path):
    """#94: "nothing in it is an item" for the amendments division - even a
    row that looks like a bare numbered line must not split the table into
    per-row chunks."""
    registry, document = _fixture_document(tmp_path, "amendments_only", "105", [
        [("Short title", False), ("1. This Act may be cited as the Amendments Fixture Act 2026.", False)],
        [
            ("LIST OF AMENDMENTS", True),
            ("Amending law", False),
            ("184.", False),
            ("Act to amend the principal enactment and other related matters connected with it.", False),
            ("In force from 1 January 2020 by order of the Minister published in the Gazette.", False),
        ],
    ])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("LIST OF AMENDMENTS", "184") not in by_key
    assert ("LIST OF AMENDMENTS", "") in by_key
    assert "In force from 1 January 2020" in by_key[("LIST OF AMENDMENTS", "")]["content"]
    # #95: the list of amendments is never addressable, so it never gets a path.
    assert by_key[("LIST OF AMENDMENTS", "")]["path"] is None


def test_body_bare_line_disabled_without_a_detected_enacting_formula(tmp_path: Path):
    """#94: a document with no confirmed front-matter boundary reads its own
    table of contents - number first, title second - as body text; every row
    there looks exactly like a real split heading to the bare-line pattern.
    Act 595 EN was the real document that surfaced this risk, back when its
    own recital ("...IT IS ENACTED by the Parliament of Malaysia", no "BE")
    went unrecognised. Reproduced here with a fixture carrying no enacting
    formula at all, since the guard cares about the absence of a confirmed
    boundary, not about which real documents currently have one."""
    registry, document = _fixture_document(tmp_path, "no_formula_toc", "106", [[
        ("Section", False),
        ("1.", False),
        ("Short title and commencement", False),
        ("2.", False),
        ("Interpretation", False),
        ("3.", False),
        ("Application", False),
        ("Application", False),
        ("3. This Act applies throughout Malaysia and comes into force on a date", False),
        ("appointed by the Minister by notification in the Gazette.", False),
    ]])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") not in by_key
    assert ("body", "2") not in by_key
    assert len(chunks) == 1
    assert "This Act applies throughout Malaysia" in by_key[("body", "3")]["content"]


def test_schedule_part_restart_does_not_collide_with_its_earlier_numbering(tmp_path: Path):
    """#94: Act 4's Fifth Schedule restarts its own paragraph numbering at
    "1." for Part II after Part I already reached a higher number -
    measured to silently discard 69,588 real characters via last-wins dedup
    the moment a schedule's paragraphs became individually addressable. The
    restart is rejected instead of colliding: its content folds into
    whatever chunk is already open, so Part I's real "1" survives rather
    than being overwritten by Part II's."""
    registry, document = _fixture_document(tmp_path, "part_restart", "107", [
        [("Short title", False), ("1. This Act may be cited as the Part Restart Fixture Act 2026.", False)],
        [
            ("FIRST SCHEDULE", True),
            ("PART I", False),
            ("1.", False),
            ("Aluminium exposure during welding of aluminium metal in reduction plants and cans.", False),
            ("2.", False),
            ("Antimony exposure during use as a flame retardant for plastics and paint.", False),
            ("PART II", False),
            ("1.", False),
            ("Acetic acid exposure during use in photographic development and dyes.", False),
        ],
    ])
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["path"]): chunk for chunk in chunks}

    assert "Aluminium" in by_key[("FIRST SCHEDULE", "sched.1/para.1")]["content"]
    assert "Antimony" in by_key[("FIRST SCHEDULE", "sched.1/para.2")]["content"]
    assert "Acetic acid" in by_key[("FIRST SCHEDULE", "sched.1/para.2")]["content"]


def test_text_before_the_first_heading_is_unassigned_not_vanished(tmp_path: Path):
    """#74: `_extract_chunks` drops any line seen before `current_num` is first
    set — today silently. `_extraction_accounting` must count those characters
    as `unassigned` rather than lose them, while agreeing with the real chunk
    output that they never make it into a chunk."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "preamble.pdf"
    preamble = "This preamble sentence sits above any numbered section and today's extractor drops it."
    _pdf(pdf_path, [
        preamble,
        "A second preamble line, also before any heading, equally unrecognised today.",
        "1. Real section text long enough to clear the minimum content floor for this fixture.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("96", "en", digest), "96", "PREAMBLE FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 1, "https://example.test/96.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    assert all(preamble not in chunk["content"] for chunk in chunks)

    with fitz.open(pdf_path) as pdf:
        accounting = _extraction_accounting(pdf, document)

    assert accounting.unassigned_chars >= len(preamble)
    assert accounting.pdf_chars == (
        accounting.assigned_chars + accounting.classified_chars + accounting.unassigned_chars
    )


@pytest.mark.parametrize("line", [
    "ENACTED by the Parliament of Malaysia as follows:",
    "BE IT ENACTED by the Seri Paduka Baginda Yang di-Pertuan",
    # Act 187: no "Seri Paduka Baginda" at all.
    "BE IT ENACTED by the Yang di-Pertuan Agong with the advice",
    # Act 245 / Act 440: a recital preface, comma placement varies.
    "NOW THEREFORE BE IT ENACTED by the Seri Paduka Baginda",
    "NOW, THEREFORE, BE IT ENACTED by the Seri Paduka",
    "NOW,THEREFORE,BE IT ENACTED by the Duli Yang Maha Mulia Seri",
    # Act 595 / Act 622 / Act 636: no "BE", actor is "the Parliament of Malaysia".
    "NOW, THEREFORE, IT IS ENACTED by the Parliament of",
    # Act 373: "HEREBY", and a different actor again (Yang di-Pertuan Agong).
    "NOW, THEREFORE, IT IS HEREBY ENACTED by the",
    # Act 747: a whole clause ("pursuant to Article 149...") sits between
    # "NOW, THEREFORE," and "IT IS ENACTED", landing it mid-line rather than
    # at the start - this is why the third alternative has no leading `^`.
    "Constitution IT IS ENACTED by the Parliament of Malaysia as",
])
def test_enacting_formula_recognised_in_english(line: str):
    assert _ENACTING_FORMULA_RE["en"].search(line.upper())


@pytest.mark.parametrize("line", [
    "First enacted 1953 (Ordinance No. 22 of 1953)",  # metadata table, not the clause
    "Section 4 of the principal Act is amended as follows:",  # a later amendment, not the opening
    "An Act to provide for matters as follows",
    # "Enacted by" alone, without "it is" ahead of it, is a plain past
    # participle elsewhere in a document (e.g. describing subsidiary
    # legislation), not this clause - the third alternative requires "IT IS".
    "Any regulations enacted by the Minister under this section",
])
def test_lines_that_are_not_the_english_enacting_formula(line: str):
    assert not _ENACTING_FORMULA_RE["en"].search(line.upper())


@pytest.mark.parametrize("line", [
    "DIPERBUAT oleh Parlimen Malaysia seperti yang berikut:",
    "MAKA INILAH DIPERBUAT UNDANG-UNDANG oleh Seri Paduka Baginda",
    # Act 659: a recital preface, mid-line rather than its own line.
    "MAKA, OLEH YANG DEMIKIAN, DIPERBUAT oleh Parlimen Malaysia seperti",
])
def test_enacting_formula_recognised_in_malay(line: str):
    assert _ENACTING_FORMULA_RE["bm"].search(line.upper())


@pytest.mark.parametrize("line", [
    # Act 587's real failure mode: a section heading that wraps onto a line
    # of its own ending in the bare word, no collocate on that line at all.
    # "Benda ... akan diperbuat" ("things done in anticipation of this Act
    # being enacted") is a transitional-provision heading, not the clause -
    # matching the bare word here is what misread this document's first 68
    # sections as front matter (see ENACTING_FORMULA_PATTERNS's comment).
    "diperbuat",
    "akan diperbuat",
    "Pertama kali diperbuat",  # "First enacted" - the metadata table, not the clause
])
def test_bare_diperbuat_is_not_the_malay_enacting_formula(line: str):
    assert not _ENACTING_FORMULA_RE["bm"].search(line.upper())


def test_front_matter_and_table_of_contents_are_classified_not_unassigned(tmp_path: Path):
    """#93: front matter and the table of contents, from page 1 to the enacting
    formula, get a name instead of falling through to `unassigned` — #74 could
    only prove that span was not silently vanishing; this proves it is
    accounted for, not just present."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "front_matter.pdf"
    front_matter = "An Act to regulate fixture matters and for purposes connected therewith."
    toc_line = "Short title and commencement"
    _pdf(pdf_path, [
        front_matter,
        toc_line,
        "ENACTED by the Parliament of Malaysia as follows:",
        "1. This Act may be cited as the Front Matter Fixture Act 2026 and comes",
        "into operation on a date the Minister appoints by notification.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("93", "en", digest), "93", "FRONT MATTER FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 1, "https://example.test/93.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    assert all(front_matter not in chunk["content"] for chunk in chunks)
    assert all(toc_line not in chunk["content"] for chunk in chunks)

    with fitz.open(pdf_path) as pdf:
        accounting = _extraction_accounting(pdf, document)
    assert accounting.pdf_chars == (
        accounting.assigned_chars + accounting.classified_chars + accounting.unassigned_chars
    )
    assert accounting.classified_chars >= len(front_matter) + len(toc_line)
    assert accounting.unassigned_chars == 0


def test_table_of_contents_row_before_the_formula_never_starts_a_chunk(tmp_path: Path):
    """#93/#97: a table-of-contents row whose number and title land on one PDF
    line matches SECTION_PATTERN exactly like a real heading — Act 602's real
    "19B. Restoration of geographical indication removed from the Register"
    TOC row is this shape. Before the enacting formula gave the extractor a
    front-matter boundary, that row started a chunk which absorbed everything
    printed after it — the rest of the table of contents, the front matter,
    even real section 1 — up to whatever line happened to match next."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "toc_collision.pdf"
    _pdf(pdf_path, [
        "An Act to regulate fixture matters and for purposes connected therewith.",
        "9. Special provision for the fixture scenario under test",
        "10.",
        "Interpretation",
        "ENACTED by the Parliament of Malaysia as follows:",
        "1. This Act may be cited as the Collision Fixture Act 2026 and comes",
        "into operation on a date the Minister appoints by notification.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("93", "en", digest), "93", "COLLISION FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 1, "https://example.test/93.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "9") not in by_key
    assert ("body", "1") in by_key
    assert "may be cited as" in by_key[("body", "1")]["content"]
    assert "Special provision" not in by_key[("body", "1")]["content"]


def test_an_enacting_formula_past_the_page_limit_does_not_gate_the_real_body(tmp_path: Path):
    """Act 136 (Contracts Act 1950, 91 pages): its own enacting formula does
    not match this pattern at all, but an APPENDIX on page 87 reprints an
    amending Act's full text, complete with that Act's own "BE IT ENACTED".
    Before `ENACTING_FORMULA_MAX_PAGE_FRACTION`, first-occurrence-wins took
    that appendix as the boundary and read the entire real body - 68 real
    sections - as front matter. This fixture reproduces the shape: a normal
    section on page 2, 29 blank filler pages, then a line that would match
    the pattern on a later page past the floor. The real section must survive
    regardless of what a much later page contains."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "late_match.pdf"
    pages: list[list[tuple[str, bool]]] = [
        [("An Act to regulate fixture matters and for purposes connected therewith.", False)],
        [
            ("1. This Act may be cited as the Late Match Fixture Act 2026 and comes", False),
            ("into operation on a date the Minister appoints by notification.", False),
        ],
    ]
    # Filler, so the appendix page below sits past the floor. Carries enough
    # text that `_is_scanned`'s density check does not mistake this fixture
    # for a scanned PDF - real filler pages, not blank ones.
    filler = [
        ("Filler prose to keep this fixture above the scanned-page density floor.", False),
        ("A second filler line, for the same reason as the first one above it.", False),
    ]
    pages.extend([filler] * 29)
    pages.append([("BE IT ENACTED by the Seri Paduka Baginda Yang di-Pertuan", False)])
    _divided_pdf(pdf_path, pages)
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("93", "en", digest), "93", "LATE MATCH FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, len(pages), "https://example.test/93-late.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key
    assert "may be cited as" in by_key[("body", "1")]["content"]


def test_a_malay_execution_clause_does_not_gate_an_english_documents_front_matter(tmp_path: Path):
    """Act 144 (en) reprints a Malay grant-form schedule whose execution clause
    starts a line with "Diperbuat" — the same word the Malay enacting-formula
    pattern anchors on. Matching per `document.language` keeps an "en"
    document's front-matter scan from ever trying that pattern, so a line
    like this deep in the body stays ordinary prose, not a false boundary
    that would swallow the real section printed ahead of it."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "diperbuat.pdf"
    _pdf(pdf_path, [
        "1. Real section text long enough to clear the minimum content floor for this fixture.",
        "Diperbuat di Kuala Lumpur pada tarikh yang dinyatakan di atas.",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("93", "en", digest), "93", "DIPERBUAT FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 1, "https://example.test/93.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key
    assert "Real section text" in by_key[("body", "1")]["content"]


def test_malay_clause_split_across_two_lines_still_finds_the_real_boundary(tmp_path: Path):
    """Act 587: the real clause - "MAKA, OLEH YANG DEMIKIAN, INILAH DIPERBUAT
    \\nUNDANG-UNDANG oleh ..." - splits its distinctive collocation across a
    line break, and a heading 73 pages later ends "...akan \\ndiperbuat" with
    nothing else on that line. A pattern that only checked one line at a time
    skipped the real clause (neither line alone carries "diperbuat undang-
    undang") and matched the bare word at the later heading instead, reading
    the entire body up to that point - sections 1 through 68 - as front
    matter. Real numbers: assigned_chars for that document fell from 117,556
    to 11,238 before this was caught. This fixture reproduces the split and
    checks the join across the line break recovers the boundary before any
    real content is lost."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "split_clause.pdf"
    _pdf(pdf_path, [
        "Suatu Akta bagi maksud fixture ujian.",
        "MAKA INILAH DIPERBUAT",
        "UNDANG-UNDANG oleh Seri Paduka Baginda Yang di-Pertuan Agong",
        "1. Akta ini bolehlah dinamakan Akta Fixture 2026 dan hendaklah",
        "berkuat kuasa pada tarikh yang ditetapkan oleh Menteri melalui Warta.",
        "Benda yang dilakukan dengan menjangkakan Akta ini akan",
        "diperbuat",
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("93", "bm", digest), "93", "AKTA FIXTURE UJIAN", "bm", asset_key(digest),
        digest, pdf_path.stat().st_size, 1, "https://example.test/93-bm.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key
    assert "Akta ini bolehlah dinamakan" in by_key[("body", "1")]["content"]
    assert all("Suatu Akta bagi maksud fixture" not in chunk["content"] for chunk in chunks)
    assert all("MAKA INILAH DIPERBUAT" not in chunk["content"] for chunk in chunks)


@pytest.mark.parametrize("pages,bucket", [
    (1, "1"), (2, "2-5"), (5, "2-5"), (6, "6-20"), (20, "6-20"),
    (21, "21-50"), (50, "21-50"), (51, "51+"), (200, "51+"),
])
def test_page_span_bucket_boundaries(pages: int, bucket: str):
    assert _page_span_bucket(pages) == bucket


def test_chunk_quality_reports_a_blob_chunks_division_and_page_span(tmp_path: Path):
    """#92: a division's own content (#89) is legitimate but still worth naming
    when it is the *only* thing a document holds — `_chunk_quality` reads the real
    `_extract_chunks` output, so it sees exactly what a document's bundle carries."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "blob_only.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Blob Fixture Act 2026 and comes into", False),
            ("operation on a date the Minister appoints by notification in the Gazette.", False),
        ],
        [
            ("SECOND SCHEDULE", True),
            ("The High Contracting Parties undertake to respect and to ensure", False),
            ("respect for the present Convention in all circumstances without any", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("97", "en", digest), "97", "BLOB FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/97.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    _run, bundle_path = extract_document(
        registry, document,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
    )
    chunks = json.loads(bundle_path.read_text(encoding="utf-8"))["chunks"]

    quality = _chunk_quality(chunks)

    assert len(quality["unnumbered_chunks"]) == 1
    blob = quality["unnumbered_chunks"][0]
    assert blob["division"] == "SECOND SCHEDULE"
    assert blob["page_start"] == 2 and blob["page_end"] == 2
    body_chunk = next(c for c in chunks if c["section_number"] == "1")
    assert quality["max_chunk_chars"] >= len(body_chunk["content"])
    assert quality["max_chunk_chars"] >= blob["chars"]


def _synthetic_chunk(
    division: str, section_number: str, content: str, page: int = 1, path: str | None = None,
) -> dict:
    if path is None:
        path = f"s.{section_number}" if division == "body" else None
    return {
        "division": division,
        "section_number": section_number,
        "path": path,
        "content": content,
        "content_sha256": content_hash(content),
        "page_start": page,
        "page_end": page,
    }


def test_diff_chunk_sets_reports_added_removed_and_changed():
    old_chunks = [
        _synthetic_chunk("body", "1", "Short title text."),
        _synthetic_chunk("body", "2", "Interpretation text that stays the same."),
        _synthetic_chunk("body", "3", "A section that gets removed in the new generation."),
    ]
    new_chunks = [
        _synthetic_chunk("body", "1", "Short title text, reworded for the new generation."),
        _synthetic_chunk("body", "2", "Interpretation text that stays the same."),
        _synthetic_chunk("body", "4", "A brand new section the new generation adds."),
    ]

    diff = diff_chunk_sets(old_chunks, new_chunks)

    assert diff["added"] == [{"division": "body", "path": "s.4"}]
    assert diff["removed"] == [{"division": "body", "path": "s.3"}]
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["path"] == "s.1"
    assert diff["changed"][0]["old_chars"] < diff["changed"][0]["new_chars"]
    assert diff["unchanged_count"] == 1


def test_diff_extraction_manifests_only_reports_documents_that_actually_changed(tmp_path: Path):
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()

    def bundle(root: Path, extraction_id: str, chunks: list[dict]) -> None:
        (root / f"{extraction_id}.chunks.json").write_text(json.dumps({"chunks": chunks}), encoding="utf-8")

    bundle(old_root, "extraction-changed-old", [_synthetic_chunk("body", "1", "Original short title.")])
    bundle(new_root, "extraction-changed-new", [_synthetic_chunk("body", "1", "Revised, longer short title.")])
    stable = [_synthetic_chunk("body", "1", "Never touched.")]
    bundle(old_root, "extraction-stable-old", stable)
    bundle(new_root, "extraction-stable-new", stable)

    def manifest(runs: list[tuple[str, str]]) -> dict:
        return {"extraction_runs": [
            {"document_id": doc_id, "extraction_id": extraction_id} for doc_id, extraction_id in runs
        ]}

    old_manifest = manifest([("doc-changed", "extraction-changed-old"), ("doc-stable", "extraction-stable-old")])
    new_manifest = manifest([("doc-changed", "extraction-changed-new"), ("doc-stable", "extraction-stable-new")])

    diffs = diff_extraction_manifests(
        old_manifest, new_manifest, old_extraction_root=old_root, new_extraction_root=new_root,
    )

    assert set(diffs) == {"doc-changed", "doc-stable"}
    assert diffs["doc-changed"]["changed"]
    assert not diffs["doc-stable"]["added"]
    assert not diffs["doc-stable"]["removed"]
    assert not diffs["doc-stable"]["changed"]


def test_toc_oracle_flags_the_real_arrangement_of_sections_banner():
    # Verbatim page-3 text from Act 12 EN (data/pdfs/en/12.pdf), one of #72's
    # cohort: PyMuPDF puts each item number on its own line, nothing after it.
    toc_text = "\n".join([
        "ARRANGEMENT OF SECTIONS",
        "Section",
        "1.",
        "Short title",
        "2.",
        "Interpretation",
        "3.",
        "Authorization to ratify amendments of Articles of Agreement of the Fund",
        "4.",
        "Payments and receipts in connection with Special Drawing Account",
    ])
    assert chunk_looks_like_table_of_contents(toc_text)


def test_toc_oracle_flags_a_bare_number_run_without_the_banner():
    # The banner alone isn't universal (a handful of older Acts lack it) — a
    # repeated run of bare "<n>." lines is table-of-contents-shaped on its own.
    bare_run = "\n".join([
        "1.", "Short title and commencement",
        "2.", "Interpretation",
        "3.", "Application",
        "4.", "Savings",
    ])
    assert chunk_looks_like_table_of_contents(bare_run)


def test_toc_oracle_does_not_flag_ordinary_body_or_schedule_prose():
    body_text = (
        "1. This Act may be cited as the Blob Fixture Act 2026 and comes into "
        "operation on a date the Minister appoints by notification in the Gazette."
    )
    schedule_text = "\n".join([
        "ARTICLE 1",
        "The High Contracting Parties undertake to respect and to ensure respect",
        "for the present Convention in all circumstances without any adverse",
        "distinction founded on sex, race, nationality or religion.",
        "ARTICLE 2",
        "In addition to the provisions implemented in peace time, the present",
        "Convention shall apply to all cases of declared war.",
    ])
    assert not chunk_looks_like_table_of_contents(body_text)
    assert not chunk_looks_like_table_of_contents(schedule_text)


def test_extract_manifest_report_carries_the_new_quality_metrics(tmp_path: Path):
    """Integration: `extract_manifest` actually wires `_chunk_quality` and the TOC
    oracle into its report, not just `_extraction_accounting`."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    pdf_path = asset_root / "quality.pdf"
    _divided_pdf(pdf_path, [
        [
            ("Short title and commencement", False),
            ("1. This Act may be cited as the Quality Fixture Act 2026 and comes", False),
            ("into operation on a date the Minister appoints by notification.", False),
        ],
        [
            ("SECOND SCHEDULE", True),
            ("The High Contracting Parties undertake to respect and to ensure", False),
            ("respect for the present Convention in all circumstances without any", False),
        ],
    ])
    digest = sha256_file(pdf_path)
    document = CorpusDocument(
        document_id("98", "en", digest), "98", "QUALITY FIXTURE ACT", "en", asset_key(digest),
        digest, pdf_path.stat().st_size, 2, "https://example.test/98.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=pdf_path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")

    _manifest, report = extract_manifest(
        registry, extraction_root=tmp_path / "extractions", sidecar_root=tmp_path / "sidecars",
    )

    item = report["documents"][0]
    assert item["status"] == "ready"
    assert len(item["unnumbered_chunks"]) == 1
    assert item["max_chunk_chars"] > 0
    assert report["totals"]["unnumbered_chunk_count"] == 1
    assert report["totals"]["unnumbered_chunk_chars"] == item["unnumbered_chunks"][0]["chars"]
    assert sum(report["chunk_size_distribution"].values()) == item["chunk_count"]
    assert report["toc_oracle"]["chunks_scanned"] == item["chunk_count"]
    assert report["toc_oracle"]["flagged"] == []


def test_upload_scope_active_skips_documents_whose_bytes_are_not_local(tmp_path: Path):
    """#57: 1,114 of the 1,124 registered documents have no bytes in git, so a
    full-scope upload is blocked by documents the first push was never meant to
    carry. --scope active has to carry the reachable set on its own."""
    from corpus.cli import _upload_objects

    asset_root = tmp_path / "assets"
    sidecar_root = tmp_path / "sidecars"
    asset_root.mkdir()
    documents = []
    for act in ("41", "42"):
        path = asset_root / f"{act}.pdf"
        _pdf(path, [
            f"Act {act} short title",
            f"1. Section one of Act {act} carries enough legal fixture text",
            "for the extractor to clear its text-layer threshold on this page.",
        ])
        digest = sha256_file(path)
        documents.append(CorpusDocument(
            document_id(act, "en", digest), act, f"ACT {act}", "en", asset_key(digest), digest,
            path.stat().st_size, 1, f"https://example.test/{act}.pdf", "", "REPRINT",
            "2026-01-01T00:00:00Z", local_path=path.name,
        ))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256",
        "documents": [item.to_dict() for item in documents],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)
    manifest, _report = extract_manifest(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=sidecar_root,
        activate_ready=True,
    )
    # Only Act 41 is activated, and Act 42's bytes then leave the working tree
    # the way an untracked en/<act>.pdf is absent from the deployed container.
    manifest["active_documents"] = [
        item for item in manifest["active_documents"] if item["act_number"] == "41"
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (asset_root / "42.pdf").unlink()
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)

    active_objects, active_errors = _upload_objects(registry, "active")
    assert active_errors == []
    assert [key for _path, key, *_ in active_objects] == [
        documents[0].asset_key,
        registry.extraction_runs[
            registry.active_documents[("41", "en")].extraction_id
        ].coordinate_sidecar.asset_key,
    ]

    _full_objects, full_errors = _upload_objects(registry, "full")
    assert any(documents[1].document_id in error for error in full_errors)


def test_receipt_coverage_counts_documents_whose_bytes_shipped(tmp_path: Path):
    """#57: a container carries the manifest but only a handful of the PDFs it
    describes, and the gap is invisible until a receipt returns 503. The boot
    line has to separate registered from reachable."""
    from corpus.coverage import receipt_coverage

    asset_root = tmp_path / "assets"
    sidecar_root = tmp_path / "sidecars"
    asset_root.mkdir()
    documents = []
    for act in ("41", "42"):
        path = asset_root / f"{act}.pdf"
        _pdf(path, [
            f"Act {act} short title",
            f"1. Section one of Act {act} carries enough legal fixture text",
            "for the extractor to clear its text-layer threshold on this page.",
        ])
        digest = sha256_file(path)
        documents.append(CorpusDocument(
            document_id(act, "en", digest), act, f"ACT {act}", "en", asset_key(digest), digest,
            path.stat().st_size, 1, f"https://example.test/{act}.pdf", "", "REPRINT",
            "2026-01-01T00:00:00Z", local_path=path.name,
        ))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256",
        "documents": [item.to_dict() for item in documents],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)
    manifest, _report = extract_manifest(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=sidecar_root,
        activate_ready=True,
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=sidecar_root)

    full = receipt_coverage(registry, delivery_mode="auto")
    assert (full.registered, full.registered_local) == (2, 2)
    assert (full.active, full.active_local, full.active_reachable) == (2, 2, 2)
    assert full.probed == 0 and "cdn=unset" in full.line()

    (asset_root / "42.pdf").unlink()
    thin = receipt_coverage(registry, delivery_mode="auto")
    assert (thin.registered, thin.registered_local) == (2, 1)
    assert (thin.active, thin.active_local, thin.active_reachable) == (2, 1, 1)
    assert "registered_local=1/2" in thin.line()


def test_receipt_coverage_counts_a_document_the_cdn_carries(tmp_path: Path, monkeypatch):
    """An uploaded document is reachable even with no local bytes, which is the
    whole point of the R2 fallback — the boot line has to say so."""
    from corpus import coverage as coverage_module

    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    path = asset_root / "43.pdf"
    _pdf(path, [
        "Act 43 short title",
        "1. Section one of Act 43 carries enough legal fixture text",
        "for the extractor to clear its text-layer threshold on this page.",
    ])
    digest = sha256_file(path)
    document = CorpusDocument(
        document_id("43", "en", digest), "43", "ACT 43", "en", asset_key(digest), digest,
        path.stat().st_size, 1, "https://example.test/43.pdf", "", "REPRINT",
        "2026-01-01T00:00:00Z", local_path=path.name,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": 2, "identity_algorithm": "sha256", "documents": [document.to_dict()],
        "extraction_runs": [], "active_documents": [], "aliases": {}, "source_observations": [],
    }), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    manifest, _report = extract_manifest(
        registry,
        extraction_root=tmp_path / "extractions",
        sidecar_root=tmp_path / "sidecars",
        activate_ready=True,
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = CorpusRegistry(manifest_path, asset_root=asset_root, sidecar_root=tmp_path / "sidecars")
    path.unlink()

    class _Response:
        headers = {
            "Content-Length": str(document.byte_size),
            "X-Amz-Meta-Sha256": document.sha256,
            "ETag": '"fixture"',
            "Content-Type": "application/pdf",
        }

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("corpus.storage.requests.head", lambda *a, **k: _Response())

    result = coverage_module.receipt_coverage(
        registry, delivery_mode="auto", cdn_base_url="https://statutes.example.test"
    )
    assert (result.registered_local, result.active_local) == (0, 0)
    assert (result.probed, result.active_remote, result.active_reachable) == (1, 1, 1)
    assert "active_cdn=1/1" in result.line()
