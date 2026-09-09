import json
from pathlib import Path

import fitz
import pytest

import scraper.step3_pdfs as step3_pdfs
from corpus.registry import CorpusRegistry


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page(width=400, height=500)
    page.insert_text((40, 60), text)
    data = document.tobytes()
    document.close()
    return data


def _metadata(*, act: str, primary_url: str, secondary_url: str = "") -> dict:
    meta = {
        "act_number": act,
        "act_type": "updated",
        "scraped_at": "2026-01-02T00:00:00+00:00",
        "detail_url": f"https://example.test/{act}?lang=BI",
        "timeline": [{"date": "01/01/2020", "log_type": "REPRINT ONLINE", "pdf_url": primary_url}],
        "latest_reprint_pdf": primary_url,
        "latest_amendment_pdf": "",
        "detail_url_bm": f"https://example.test/{act}?lang=BM" if secondary_url else "",
        "timeline_bm": [{"date": "01/01/2020", "log_type": "REPRINT ONLINE", "pdf_url": secondary_url}] if secondary_url else [],
        "latest_reprint_pdf_bm": secondary_url,
        "latest_amendment_pdf_bm": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    return meta


def test_pick_urls_single_language_act_unchanged():
    meta = _metadata(act="1", primary_url="https://example.test/1/EN.pdf")
    assert step3_pdfs._pick_urls(meta) == [("https://example.test/1/EN.pdf", "reprint", None)]


def test_pick_urls_dual_language_act_returns_both():
    meta = _metadata(act="1", primary_url="https://example.test/1/EN.pdf", secondary_url="https://example.test/1/BM.pdf")
    picks = step3_pdfs._pick_urls(meta)
    assert picks == [
        ("https://example.test/1/EN.pdf", "reprint", None),
        ("https://example.test/1/BM.pdf", "reprint_bm", "bm"),
    ]


def test_pick_urls_skips_identical_secondary_url():
    meta = _metadata(act="1", primary_url="https://example.test/1/SAME.pdf", secondary_url="https://example.test/1/SAME.pdf")
    assert step3_pdfs._pick_urls(meta) == [("https://example.test/1/SAME.pdf", "reprint", None)]


def test_pick_urls_no_reprint_returns_empty():
    meta = {"act_number": "2", "latest_reprint_pdf": "", "latest_amendment_pdf": "https://example.test/amend.pdf"}
    assert step3_pdfs._pick_urls(meta) == []


class _FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.headers = {"Content-Type": "application/pdf"}
        self._content = content

    def iter_content(self, chunk_size):
        yield self._content


class _FakeDownloadSession:
    def __init__(self, url_to_bytes: dict[str, bytes]):
        self._url_to_bytes = url_to_bytes
        self.requested: list[str] = []

    def get(self, url, timeout=None, stream=None):
        self.requested.append(url)
        content = self._url_to_bytes.get(url)
        if content is None:
            return _FakeResponse(404)
        return _FakeResponse(200, content)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(step3_pdfs.time, "sleep", lambda *_: None)


def _wire(tmp_path, monkeypatch, *, index, metadata_files):
    metadata_dir = tmp_path / "acts_metadata"
    metadata_dir.mkdir()
    for name, data in metadata_files.items():
        (metadata_dir / name).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(step3_pdfs, "METADATA_DIR", str(metadata_dir))

    pdf_root = tmp_path / "pdfs"
    monkeypatch.setattr(step3_pdfs, "PDF_EN_DIR", str(pdf_root / "en"))
    monkeypatch.setattr(step3_pdfs, "DOWNLOAD_REPORT", str(tmp_path / "download_report.json"))

    index_path = tmp_path / "acts_index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step3_pdfs, "INDEX_FILE", str(index_path))
    return pdf_root


def test_run_step3_registers_both_languages_for_a_dual_language_act(tmp_path, monkeypatch):
    en_bytes = _pdf_bytes("Short title\n1. English section text long enough to be a real fixture.")
    bm_bytes = _pdf_bytes("Tajuk ringkas\n1. Kandungan seksyen Bahasa Malaysia untuk ujian pendaftaran.")
    meta = _metadata(
        act="9", primary_url="https://example.test/9/EN.pdf", secondary_url="https://example.test/9/BM.pdf",
    )
    index = {"acts": [{"act_number": "9", "title_en": "FIXTURE ACT", "title_bm": "AKTA CONTOH"}]}
    pdf_root = _wire(tmp_path, monkeypatch, index=index, metadata_files={"9.json": meta})

    session = _FakeDownloadSession({
        "https://example.test/9/EN.pdf": en_bytes,
        "https://example.test/9/BM.pdf": bm_bytes,
    })
    monkeypatch.setattr("scraper.session.build_download_session", lambda: session)

    step3_pdfs.run_step3()

    registry = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    documents = list(registry.documents.values())
    assert {d.language for d in documents} == {"en", "bm"}
    assert {d.act_number for d in documents} == {"9"}
    en_doc = next(d for d in documents if d.language == "en")
    bm_doc = next(d for d in documents if d.language == "bm")
    assert en_doc.document_id != bm_doc.document_id
    assert bm_doc.act_title == "AKTA CONTOH"

    report = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report["downloaded"] == 2
    assert report["failed"] == 0

    first_ids = {d.document_id for d in documents}

    # Re-running is idempotent: same two document_ids, now counted as unchanged.
    session.requested.clear()
    step3_pdfs.run_step3()
    registry_again = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    second_ids = {d.document_id for d in registry_again.documents.values()}
    assert second_ids == first_ids
    report_again = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report_again["verified_unchanged"] == 2
    assert report_again["downloaded"] == 0


def test_run_step3_single_language_act_registers_one_document(tmp_path, monkeypatch):
    en_bytes = _pdf_bytes("Short title\n1. English-only fixture act, long enough for a real section.")
    meta = _metadata(act="10", primary_url="https://example.test/10/EN.pdf")
    index = {"acts": [{"act_number": "10", "title_en": "SOLO ACT", "title_bm": "AKTA SOLO"}]}
    pdf_root = _wire(tmp_path, monkeypatch, index=index, metadata_files={"10.json": meta})

    session = _FakeDownloadSession({"https://example.test/10/EN.pdf": en_bytes})
    monkeypatch.setattr("scraper.session.build_download_session", lambda: session)

    step3_pdfs.run_step3()

    registry = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    documents = list(registry.documents.values())
    assert len(documents) == 1
    assert documents[0].language == "en"
