import hashlib
import json
from pathlib import Path

import fitz
import pytest

from citation_receipts.locator import locate_evidence
from corpus.extraction import _DIVISION_RE, _is_heading_case, extract_document, extract_manifest
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
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    assert ("body", "1") in by_key and ("FIRST SCHEDULE", "1") in by_key
    assert "may be cited as" in by_key[("body", "1")]["content"]
    assert "liquidator" in by_key[("FIRST SCHEDULE", "1")]["content"]
    assert by_key[("body", "2")]["division"] == "body"
    # The heading is a boundary, not content: it belongs to neither paragraph.
    assert "FIRST SCHEDULE" not in by_key[("body", "2")]["content"]


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
    by_key = {(chunk["division"], chunk["section_number"]): chunk for chunk in chunks}

    # The copy on page 1 is the table of contents; the division starts on page 3.
    assert by_key[("body", "1")]["page_start"] == 2
    assert by_key[("FIRST SCHEDULE", "1")]["page_start"] == 3
