import json
from pathlib import Path

import pytest

import scraper.step2_detail as step2_detail
from scraper.config import DETAIL_URL


def _detail_html(date: str, log_type: str, pdf_name: str) -> str:
    pdf_src = (
        f"pdfjs/web/viewer.html?file=../../../ilims/upload/portal/akta/"
        f"outputaktap/1_BI/{pdf_name}&embedded=true"
    )
    return f"""
    <html><body>
    <a data-date="{date}" data-project-id="1" data-log-type="{log_type}"></a>
    <li data-date="{date}"><iframe data-src="{pdf_src}"></iframe></li>
    </body></html>
    """


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"data": []}


class _FakeSession:
    """Maps exact URLs to canned HTML. Any unmapped URL 404s.

    Passing None as the mapped value simulates a page that fails to load
    (used to assert a code path never issues a particular request).
    """

    def __init__(self, pages: dict[str, str | None]):
        self._pages = pages
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        if url not in self._pages or self._pages[url] is None:
            return _FakeResponse(404)
        return _FakeResponse(200, self._pages[url])

    def post(self, url, data=None, timeout=None):
        return _FakeResponse(200)


class _FlakySession(_FakeSession):
    """Like _FakeSession, but a URL mapped to FAILS 500s instead of 404ing —
    simulates a transient failure that is not a real "page doesn't exist"."""

    FAILS = object()

    def get(self, url, timeout=None):
        self.requested.append(url)
        if self._pages.get(url) is self.FAILS:
            return _FakeResponse(500)
        if url not in self._pages or self._pages[url] is None:
            return _FakeResponse(404)
        return _FakeResponse(200, self._pages[url])


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(step2_detail.time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def _metadata_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(tmp_path))
    return tmp_path


def _bi_url(act: str) -> str:
    return f"{DETAIL_URL}?act={act}&lang=BI"


def _bm_url(act: str) -> str:
    return f"{DETAIL_URL}?act={act}&lang=BM"


def test_scrape_act_fetches_both_languages_when_both_exist():
    session = _FakeSession({
        _bi_url("1"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT1-EN.pdf"),
        _bm_url("1"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT1-BM.pdf"),
    })

    result = step2_detail.scrape_act(session, "1", "updated")

    assert result["detail_url"] == _bi_url("1")
    assert result["latest_reprint_pdf"].endswith("ACT1-EN.pdf")
    assert result["detail_url_bm"] == _bm_url("1")
    assert result["latest_reprint_pdf_bm"].endswith("ACT1-BM.pdf")


def test_scrape_act_leaves_bm_fields_empty_when_no_bm_version_exists():
    session = _FakeSession({
        _bi_url("2"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT2-EN.pdf"),
        _bm_url("2"): None,
    })

    result = step2_detail.scrape_act(session, "2", "updated")

    assert result["latest_reprint_pdf"].endswith("ACT2-EN.pdf")
    assert result["detail_url_bm"] == ""
    assert result["timeline_bm"] == []
    assert result["latest_reprint_pdf_bm"] == ""


def test_scrape_act_bm_only_act_does_not_double_fetch():
    """BI totally unavailable -> falls back to BM as the primary, exactly as
    before. No secondary fetch is attempted (it would just re-fetch the same
    page), so detail_url_bm stays empty even though the Act is BM."""
    session = _FakeSession({
        _bi_url("144"): None,
        _bm_url("144"): _detail_html("01/01/2020", "REPRINT ONLINE", "AKTA144.pdf"),
    })

    result = step2_detail.scrape_act(session, "144", "updated")

    assert result["detail_url"] == _bm_url("144")
    assert result["latest_reprint_pdf"].endswith("AKTA144.pdf")
    assert result["detail_url_bm"] == ""
    assert result["timeline_bm"] == []
    # Only one BM request was made — the primary fallback, not a second probe.
    assert session.requested.count(_bm_url("144")) == 1


def test_scrape_act_offline_html_override_skips_secondary_fetch():
    session = _FakeSession({_bm_url("3"): "should never be requested"})
    html = _detail_html("01/01/2020", "REPRINT ONLINE", "ACT3-EN.pdf")

    result = step2_detail.scrape_act(session, "3", "updated", html=html)

    assert result["latest_reprint_pdf"].endswith("ACT3-EN.pdf")
    assert result["detail_url_bm"] == ""
    assert session.requested == []


def test_backfill_bm_variant_never_touches_primary_fields():
    existing = {
        "act_number": "5",
        "act_type": "updated",
        "scraped_at": "2026-01-01T00:00:00+00:00",
        "detail_url": _bi_url("5"),
        "timeline": [{"date": "01/01/2019", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT5.pdf"}],
        "latest_reprint_pdf": "https://old/ACT5.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    session = _FakeSession({
        _bm_url("5"): _detail_html("01/01/2019", "REPRINT ONLINE", "AKTA5.pdf"),
    })

    result, made_request = step2_detail.backfill_bm_variant(session, "5", existing)

    assert made_request is True
    assert result["detail_url"] == existing["detail_url"]
    assert result["timeline"] == existing["timeline"]
    assert result["latest_reprint_pdf"] == existing["latest_reprint_pdf"]
    assert result["detail_url_bm"] == _bm_url("5")
    assert result["latest_reprint_pdf_bm"].endswith("AKTA5.pdf")


def test_backfill_bm_variant_skips_network_for_bm_only_acts():
    existing = {
        "act_number": "144",
        "detail_url": _bm_url("144"),
        "timeline": [],
        "latest_reprint_pdf": "https://old/AKTA144.pdf",
        "latest_amendment_pdf": "",
    }
    session = _FakeSession({})  # any request would 404 and be visible via .requested

    result, made_request = step2_detail.backfill_bm_variant(session, "144", existing)

    assert made_request is False
    assert session.requested == []
    assert result["detail_url_bm"] == ""
    assert result["latest_reprint_pdf"] == existing["latest_reprint_pdf"]


def test_run_step2_backfills_old_format_files_without_touching_primary(tmp_path, monkeypatch):
    index = {"acts": [{"act_number": "7", "act_type": "updated", "title_en": "FIXTURE"}]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    old_format = {
        "act_number": "7",
        "act_type": "updated",
        "detail_url": _bi_url("7"),
        "timeline": [{"date": "01/01/2018", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT7.pdf"}],
        "latest_reprint_pdf": "https://old/ACT7.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    (metadata_dir / "7.json").write_text(json.dumps(old_format), encoding="utf-8")

    session = _FakeSession({_bm_url("7"): _detail_html("01/01/2018", "REPRINT ONLINE", "AKTA7.pdf")})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)

    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "7.json").read_text(encoding="utf-8"))
    assert saved["detail_url"] == old_format["detail_url"]
    assert saved["latest_reprint_pdf"] == old_format["latest_reprint_pdf"]
    assert saved["detail_url_bm"] == _bm_url("7")
    assert saved["latest_reprint_pdf_bm"].endswith("AKTA7.pdf")

    # Second run is a true no-op: file already carries detail_url_bm.
    session.requested.clear()
    step2_detail.run_step2()
    assert session.requested == []


def test_scrape_act_secondary_transient_failure_is_not_cached_as_absent():
    """A 500/timeout on the BM fetch must not look like "confirmed no BM
    version" — that would permanently block the backfill from ever retrying."""
    session = _FlakySession({
        _bi_url("6"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT6-EN.pdf"),
        _bm_url("6"): _FlakySession.FAILS,
    })

    result = step2_detail.scrape_act(session, "6", "updated")

    assert result["latest_reprint_pdf"].endswith("ACT6-EN.pdf")
    assert "detail_url_bm" not in result


def test_run_step2_backfill_retries_after_transient_bm_failure(tmp_path, monkeypatch):
    index = {"acts": [{"act_number": "8", "act_type": "updated", "title_en": "FIXTURE"}]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    old_format = {
        "act_number": "8",
        "act_type": "updated",
        "detail_url": _bi_url("8"),
        "timeline": [{"date": "01/01/2018", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT8.pdf"}],
        "latest_reprint_pdf": "https://old/ACT8.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    (metadata_dir / "8.json").write_text(json.dumps(old_format), encoding="utf-8")

    flaky = _FlakySession({_bm_url("8"): _FlakySession.FAILS})
    monkeypatch.setattr("scraper.session.build_session", lambda: flaky)
    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "8.json").read_text(encoding="utf-8"))
    assert "detail_url_bm" not in saved

    # Once the page is reachable again, a later run backfills it instead of
    # having given up permanently.
    healthy = _FakeSession({_bm_url("8"): _detail_html("01/01/2018", "REPRINT ONLINE", "AKTA8.pdf")})
    monkeypatch.setattr("scraper.session.build_session", lambda: healthy)
    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "8.json").read_text(encoding="utf-8"))
    assert saved["detail_url_bm"] == _bm_url("8")


def test_run_step2_corrupt_metadata_file_does_not_abort_sweep(tmp_path, monkeypatch):
    index = {"acts": [
        {"act_number": "20", "act_type": "updated", "title_en": "CORRUPT FIXTURE"},
        {"act_number": "21", "act_type": "updated", "title_en": "GOOD FIXTURE"},
    ]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    (metadata_dir / "20.json").write_text("{not valid json", encoding="utf-8")

    session = _FakeSession({
        _bi_url("20"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT20-EN.pdf"),
        _bm_url("20"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT20-BM.pdf"),
        _bi_url("21"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT21-EN.pdf"),
        _bm_url("21"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT21-BM.pdf"),
    })
    monkeypatch.setattr("scraper.session.build_session", lambda: session)

    step2_detail.run_step2()  # must not raise despite the corrupt file

    act20 = json.loads((metadata_dir / "20.json").read_text(encoding="utf-8"))
    act21 = json.loads((metadata_dir / "21.json").read_text(encoding="utf-8"))
    assert act20["latest_reprint_pdf"].endswith("ACT20-EN.pdf")
    assert act21["latest_reprint_pdf"].endswith("ACT21-EN.pdf")
