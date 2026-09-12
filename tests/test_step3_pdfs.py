import json
import threading
import time as real_time
from pathlib import Path

import fitz
import pytest
import requests

import scraper.step3_pdfs as step3_pdfs
from corpus.registry import CorpusRegistry

# Bound before _no_sleep replaces time.sleep on the shared module object,
# so the fake host can still hold a request open long enough for
# overlapping workers to be observable.
_REAL_SLEEP = real_time.sleep


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
    def __init__(self, status_code, content=b"", content_type="application/pdf"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self._content = content

    def iter_content(self, chunk_size):
        yield self._content


class _FakeHost:
    """Scripted stand-in for the AGC asset host.

    Each URL maps to a list of outcomes consumed in order, the last one
    repeating. An outcome is bytes (a 200 carrying a PDF), an exception to
    raise, or a ready-made _FakeResponse. An unscripted URL answers 404.
    """

    def __init__(self, script: dict):
        self._script = {
            url: (list(v) if isinstance(v, list) else [v]) for url, v in script.items()
        }
        self._lock = threading.Lock()
        self._in_flight = 0
        self.requested: list[str] = []
        self.sessions: list["_FakeDownloadSession"] = []
        self.peak_in_flight = 0

    def session(self) -> "_FakeDownloadSession":
        session = _FakeDownloadSession(self)
        with self._lock:
            self.sessions.append(session)
        return session

    def next_outcome(self, url):
        with self._lock:
            self.requested.append(url)
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
            outcomes = self._script.get(url)
            outcome = None if not outcomes else (
                outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
            )
        # Held open briefly so overlapping workers are visible in peak_in_flight.
        _REAL_SLEEP(0.01)
        with self._lock:
            self._in_flight -= 1
        return outcome if outcome is not None else _FakeResponse(404, content_type="text/html")


class _FakeDownloadSession:
    def __init__(self, host: _FakeHost):
        self._host = host
        self.threads: set[int] = set()
        self.closed = False

    def get(self, url, timeout=None, stream=None):
        self.threads.add(threading.get_ident())
        outcome = self._host.next_outcome(url)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, bytes):
            return _FakeResponse(200, outcome)
        return outcome

    def close(self):
        self.closed = True


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

    host = _FakeHost({
        "https://example.test/9/EN.pdf": en_bytes,
        "https://example.test/9/BM.pdf": bm_bytes,
    })
    monkeypatch.setattr("scraper.session.build_download_session", host.session)

    step3_pdfs.run_step3()

    registry = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    documents = list(registry.documents.values())
    assert {d.language for d in documents} == {"en", "bm"}
    assert {d.act_number for d in documents} == {"9"}
    en_doc = next(d for d in documents if d.language == "en")
    bm_doc = next(d for d in documents if d.language == "bm")
    assert en_doc.document_id != bm_doc.document_id
    assert bm_doc.act_title == "AKTA CONTOH"
    assert en_doc.detail_url == meta["detail_url"]
    assert bm_doc.detail_url == meta["detail_url_bm"]
    assert bm_doc.detail_url != en_doc.detail_url

    report = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report["downloaded"] == 2
    assert report["failed"] == 0

    first_ids = {d.document_id for d in documents}

    # Re-running is idempotent: same two document_ids, now counted as unchanged.
    host.requested.clear()
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

    host = _FakeHost({"https://example.test/10/EN.pdf": en_bytes})
    monkeypatch.setattr("scraper.session.build_download_session", host.session)

    step3_pdfs.run_step3()

    registry = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    documents = list(registry.documents.values())
    assert len(documents) == 1
    assert documents[0].language == "en"


def test_read_timeout_is_retried_rather_than_swallowed(tmp_path):
    url = "https://example.test/slow.pdf"
    host = _FakeHost({url: [requests.exceptions.ReadTimeout("read timed out"), b"%PDF-1.4 body"]})
    dest = tmp_path / "slow.pdf"

    outcome = step3_pdfs._download_pdf(host.session(), url, dest)

    assert outcome.ok
    assert outcome.reason is None
    assert dest.read_bytes() == b"%PDF-1.4 body"
    assert len(host.requested) == 2


def test_exhausted_read_timeouts_report_the_timeout_as_the_reason(tmp_path):
    url = "https://example.test/dead.pdf"
    host = _FakeHost({url: requests.exceptions.ReadTimeout("read timed out")})

    outcome = step3_pdfs._download_pdf(host.session(), url, tmp_path / "dead.pdf")

    assert not outcome.ok
    assert outcome.reason == "read timeout"
    assert len(host.requested) == len(step3_pdfs.RETRY_DELAYS) + 1


def test_5xx_with_non_pdf_body_is_a_permanent_miss_and_spends_no_retries(tmp_path):
    # The AGC asset host answers a missing file with 500 + text/html, so there
    # is nothing to come back for.
    url = "https://example.test/missing.pdf"
    host = _FakeHost({url: _FakeResponse(500, b"<html>500</html>", content_type="text/html")})

    outcome = step3_pdfs._download_pdf(host.session(), url, tmp_path / "missing.pdf")

    assert not outcome.ok
    assert outcome.reason == "permanent miss: HTTP 500 (text/html)"
    assert len(host.requested) == 1


def test_5xx_carrying_a_pdf_still_uses_the_retry_budget(tmp_path):
    url = "https://example.test/flaky.pdf"
    host = _FakeHost({url: [_FakeResponse(500, content_type="application/pdf"), b"%PDF-1.4 ok"]})

    outcome = step3_pdfs._download_pdf(host.session(), url, tmp_path / "flaky.pdf")

    assert outcome.ok
    assert len(host.requested) == 2


def test_rate_limiting_halves_concurrency_and_keeps_going(tmp_path):
    url = "https://example.test/busy.pdf"
    throttle = step3_pdfs._Throttle(8)
    host = _FakeHost({url: [_FakeResponse(503, content_type="text/html"), b"%PDF-1.4 ok"]})

    outcome = step3_pdfs._download_pdf(host.session(), url, tmp_path / "busy.pdf", throttle=throttle)

    assert outcome.ok
    assert throttle.limit == 4


def test_throttle_never_drops_below_one_permit():
    throttle = step3_pdfs._Throttle(8)
    for _ in range(10):
        throttle.back_off()
    assert throttle.limit == 1


def _many_acts(count: int) -> tuple[dict, dict, dict]:
    metadata_files, urls, index_acts = {}, {}, []
    for n in range(1, count + 1):
        url = f"https://example.test/{n}/EN.pdf"
        metadata_files[f"{n}.json"] = _metadata(act=str(n), primary_url=url)
        urls[url] = _pdf_bytes(f"Short title\n1. Fixture act {n} with enough text to be a real section.")
        index_acts.append({"act_number": str(n), "title_en": f"ACT {n}", "title_bm": f"AKTA {n}"})
    return metadata_files, urls, {"acts": index_acts}


def test_workers_never_share_a_session_and_fetches_overlap(tmp_path, monkeypatch):
    metadata_files, urls, index = _many_acts(12)
    _wire(tmp_path, monkeypatch, index=index, metadata_files=metadata_files)
    monkeypatch.setattr(step3_pdfs, "DOWNLOAD_CONCURRENCY", 4)

    host = _FakeHost(urls)
    monkeypatch.setattr("scraper.session.build_download_session", host.session)

    step3_pdfs.run_step3()

    assert host.peak_in_flight > 1, "downloads ran serially"
    assert host.peak_in_flight <= 4, "exceeded DOWNLOAD_CONCURRENCY"
    for session in host.sessions:
        assert len(session.threads) <= 1, "a session was used by two workers"
        assert session.closed


def test_concurrent_run_registers_every_act_and_keeps_identity_stable(tmp_path, monkeypatch):
    metadata_files, urls, index = _many_acts(12)
    pdf_root = _wire(tmp_path, monkeypatch, index=index, metadata_files=metadata_files)
    monkeypatch.setattr(step3_pdfs, "DOWNLOAD_CONCURRENCY", 4)

    monkeypatch.setattr("scraper.session.build_download_session", _FakeHost(urls).session)
    step3_pdfs.run_step3()

    registry = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    first = {d.act_number: d.document_id for d in registry.documents.values()}
    assert len(first) == 12

    monkeypatch.setattr("scraper.session.build_download_session", _FakeHost(urls).session)
    step3_pdfs.run_step3()

    again = CorpusRegistry(pdf_root / "manifest.json", asset_root=pdf_root)
    assert {d.act_number: d.document_id for d in again.documents.values()} == first

    report = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report["verified_unchanged"] == 12
    assert report["downloaded"] == 0


def test_every_failure_in_the_report_carries_a_reason(tmp_path, monkeypatch):
    absent = "https://example.test/404/EN.pdf"
    html = "https://example.test/html/EN.pdf"
    gone = "https://example.test/gone/EN.pdf"
    metadata_files = {
        "1.json": _metadata(act="1", primary_url=absent),
        "2.json": _metadata(act="2", primary_url=html),
        "3.json": _metadata(act="3", primary_url=gone),
    }
    index = {"acts": [{"act_number": a, "title_en": f"ACT {a}", "title_bm": ""} for a in ("1", "2", "3")]}
    _wire(tmp_path, monkeypatch, index=index, metadata_files=metadata_files)

    host = _FakeHost({
        html: _FakeResponse(200, b"<html>not a pdf</html>", content_type="text/html"),
        gone: _FakeResponse(500, b"<html>500</html>", content_type="text/html"),
    })
    monkeypatch.setattr("scraper.session.build_download_session", host.session)

    step3_pdfs.run_step3()

    report = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report["failed"] == 3
    reasons = {f["act_number"]: f["reason"] for f in report["failures"]}
    assert reasons["1"] == "404"
    assert reasons["2"] == "unexpected content type: text/html"
    assert reasons["3"] == "permanent miss: HTTP 500 (text/html)"


def test_staging_is_empty_after_a_run(tmp_path, monkeypatch):
    metadata_files, urls, index = _many_acts(6)
    pdf_root = _wire(tmp_path, monkeypatch, index=index, metadata_files=metadata_files)
    monkeypatch.setattr("scraper.session.build_download_session", _FakeHost(urls).session)

    step3_pdfs.run_step3()

    assert list((pdf_root / "staging").glob("*.pdf")) == []


def test_an_unexpected_worker_error_is_recorded_not_fatal(tmp_path, monkeypatch):
    metadata_files, urls, index = _many_acts(3)
    _wire(tmp_path, monkeypatch, index=index, metadata_files=metadata_files)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("scraper.session.build_download_session", _FakeHost(urls).session)
    monkeypatch.setattr(step3_pdfs, "_download_pdf", _explode)

    step3_pdfs.run_step3()

    report = json.loads(Path(step3_pdfs.DOWNLOAD_REPORT).read_text(encoding="utf-8"))
    assert report["failed"] == 3
    assert all(f["reason"] == "RuntimeError: disk on fire" for f in report["failures"])
