import json
from pathlib import Path

import pytest

import scraper.step2_detail as step2_detail
from tests.conftest import FAKE_RESPONSE_KEY, encrypt_envelope


def _detail_html(date: str, log_type: str, pdf_name: str) -> str:
    pdf_src = (
        f"pdfjs/web/viewer.html?file=../../../ilims/upload/portal/akta/"
        f"outputaktap/1_BI/{pdf_name}&embedded=true"
    )
    return f"""
    <html><body><div id="wrapper">
    <a data-date="{date}" data-project-id="1" data-log-type="{log_type}"></a>
    <li data-date="{date}"><iframe data-src="{pdf_src}"></iframe></li>
    </div></body></html>
    """


def _empty_detail_html() -> str:
    """A genuine detail page (carries the site wrapper) that lists nothing."""
    return '<html><body><div id="wrapper"><div class="timeline-empty"></div></div></body></html>'


# AGC's real response for a rejected/malformed request: HTTP 200, 15-byte body,
# no HTML at all — see issue #63.
_REJECTED = "Invalid request"

_EMPTY_SUBSID = encrypt_envelope({"recordsTotal": 0, "records": []})


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body if json_body is not None else _EMPTY_SUBSID

    def json(self):
        return self._json_body


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


def _en_link(act: str) -> str:
    return f"https://lom.agc.gov.my/processFile.php?isDirect=1&token=en-{act}"


def _bm_link(act: str) -> str:
    return f"https://lom.agc.gov.my/processFile.php?isDirect=1&token=bm-{act}"


def _scrape(session, act_number, act_type="updated", **kwargs):
    return step2_detail.scrape_act(session, act_number, act_type, FAKE_RESPONSE_KEY, **kwargs)


def test_scrape_act_fetches_both_languages_when_both_exist():
    session = _FakeSession({
        _en_link("1"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT1-EN.pdf"),
        _bm_link("1"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT1-BM.pdf"),
    })

    result = _scrape(session, "1", link_en=_en_link("1"), link_bm=_bm_link("1"))

    assert result["detail_url"] == _en_link("1")
    assert result["latest_reprint_pdf"].endswith("ACT1-EN.pdf")
    assert result["detail_url_bm"] == _bm_link("1")
    assert result["latest_reprint_pdf_bm"].endswith("ACT1-BM.pdf")


def test_scrape_act_no_bm_link_in_listing_is_confirmed_absent():
    """When the listing itself carries no Malay link, that's authoritative —
    no HTTP probe needed, and the *_bm fields are confirmed-absent immediately."""
    session = _FakeSession({
        _en_link("2"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT2-EN.pdf"),
    })

    result = _scrape(session, "2", link_en=_en_link("2"), link_bm="")

    assert result["latest_reprint_pdf"].endswith("ACT2-EN.pdf")
    assert result["detail_url_bm"] == ""
    assert result["timeline_bm"] == []
    assert result["latest_reprint_pdf_bm"] == ""
    assert _bm_link("2") not in session.requested


def test_scrape_act_bm_only_act_does_not_fetch_english():
    """An Act covers only Malay per the listing (no English link at all) —
    the Malay document becomes the primary (unsuffixed) slot, exactly as
    before, and there is no separate secondary to fetch."""
    session = _FakeSession({
        _bm_link("144"): _detail_html("01/01/2020", "REPRINT ONLINE", "AKTA144.pdf"),
    })

    result = _scrape(session, "144", link_en="", link_bm=_bm_link("144"))

    assert result["detail_url"] == _bm_link("144")
    assert result["latest_reprint_pdf"].endswith("AKTA144.pdf")
    assert result["detail_url_bm"] == ""
    assert result["timeline_bm"] == []
    assert session.requested.count(_bm_link("144")) == 1
    assert _en_link("144") not in session.requested


def test_scrape_act_offline_html_override_skips_secondary_fetch():
    session = _FakeSession({_bm_link("3"): "should never be requested"})
    html = _detail_html("01/01/2020", "REPRINT ONLINE", "ACT3-EN.pdf")

    result = _scrape(session, "3", html=html, link_bm=_bm_link("3"))

    assert result["latest_reprint_pdf"].endswith("ACT3-EN.pdf")
    assert result["detail_url_bm"] == ""
    assert session.requested == []


def test_backfill_bm_variant_never_touches_primary_fields():
    existing = {
        "act_number": "5",
        "act_type": "updated",
        "scraped_at": "2026-01-01T00:00:00+00:00",
        "detail_url": _en_link("5"),
        "timeline": [{"date": "01/01/2019", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT5.pdf"}],
        "latest_reprint_pdf": "https://old/ACT5.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    session = _FakeSession({
        _bm_link("5"): _detail_html("01/01/2019", "REPRINT ONLINE", "AKTA5.pdf"),
    })

    result, made_request = step2_detail.backfill_bm_variant(session, "5", existing, link_bm=_bm_link("5"))

    assert made_request is True
    assert result["detail_url"] == existing["detail_url"]
    assert result["timeline"] == existing["timeline"]
    assert result["latest_reprint_pdf"] == existing["latest_reprint_pdf"]
    assert result["detail_url_bm"] == _bm_link("5")
    assert result["latest_reprint_pdf_bm"].endswith("AKTA5.pdf")


def test_backfill_bm_variant_skips_network_for_bm_only_acts():
    """Old-format file whose primary was itself the lang=BM fallback (from
    before issue #64) — recognized by the legacy `lang=BM` URL shape."""
    existing = {
        "act_number": "144",
        "detail_url": "https://lom.agc.gov.my/act-detail.php?act=144&lang=BM",
        "timeline": [],
        "latest_reprint_pdf": "https://old/AKTA144.pdf",
        "latest_amendment_pdf": "",
    }
    session = _FakeSession({})  # any request would 404 and be visible via .requested

    result, made_request = step2_detail.backfill_bm_variant(session, "144", existing, link_bm=_bm_link("144"))

    assert made_request is False
    assert session.requested == []
    assert result["detail_url_bm"] == ""
    assert result["latest_reprint_pdf"] == existing["latest_reprint_pdf"]


def test_backfill_bm_variant_no_link_in_current_listing_is_confirmed_absent():
    existing = {
        "act_number": "6",
        "detail_url": _en_link("6"),
        "timeline": [],
        "latest_reprint_pdf": "https://old/ACT6.pdf",
        "latest_amendment_pdf": "",
    }
    session = _FakeSession({})

    result, made_request = step2_detail.backfill_bm_variant(session, "6", existing, link_bm="")

    assert made_request is False
    assert session.requested == []
    assert result["detail_url_bm"] == ""


def test_run_step2_backfills_old_format_files_without_touching_primary(tmp_path, monkeypatch):
    index = {"acts": [{"act_number": "7", "act_type": "updated", "title_en": "FIXTURE",
                        "title_link_en": _en_link("7"), "title_link_bm": _bm_link("7")}]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    old_format = {
        "act_number": "7",
        "act_type": "updated",
        "detail_url": _en_link("7"),
        "timeline": [{"date": "01/01/2018", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT7.pdf"}],
        "latest_reprint_pdf": "https://old/ACT7.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    (metadata_dir / "7.json").write_text(json.dumps(old_format), encoding="utf-8")

    session = _FakeSession({_bm_link("7"): _detail_html("01/01/2018", "REPRINT ONLINE", "AKTA7.pdf")})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "7.json").read_text(encoding="utf-8"))
    assert saved["detail_url"] == old_format["detail_url"]
    assert saved["latest_reprint_pdf"] == old_format["latest_reprint_pdf"]
    assert saved["detail_url_bm"] == _bm_link("7")
    assert saved["latest_reprint_pdf_bm"].endswith("AKTA7.pdf")

    # Second run is a true no-op: file already carries detail_url_bm.
    session.requested.clear()
    step2_detail.run_step2()
    assert session.requested == []


def test_scrape_act_secondary_transient_failure_is_not_cached_as_absent():
    """A 500/timeout on the BM fetch must not look like "confirmed no BM
    version" — that would permanently block the backfill from ever retrying."""
    session = _FlakySession({
        _en_link("6"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT6-EN.pdf"),
        _bm_link("6"): _FlakySession.FAILS,
    })

    result = _scrape(session, "6", link_en=_en_link("6"), link_bm=_bm_link("6"))

    assert result["latest_reprint_pdf"].endswith("ACT6-EN.pdf")
    assert "detail_url_bm" not in result


def test_scrape_act_bm_rejection_body_is_not_cached_as_absent(caplog):
    """AGC answering with HTTP 200 + 'Invalid request' — e.g. a stale token —
    must not be read as 'confirmed no BM version'."""
    session = _FakeSession({
        _en_link("9"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT9-EN.pdf"),
        _bm_link("9"): _REJECTED,
    })

    with caplog.at_level("WARNING"):
        result = _scrape(session, "9", link_en=_en_link("9"), link_bm=_bm_link("9"))

    assert result["latest_reprint_pdf"].endswith("ACT9-EN.pdf")
    assert "detail_url_bm" not in result
    assert any("not a detail page" in r.message for r in caplog.records)


def test_scrape_act_primary_rejection_is_transient_failure(caplog):
    """English has a link per the listing, but the fetch comes back rejected
    (stale token) — the whole Act is transient-failed, never silently
    demoted to a Malay-primary document."""
    session = _FakeSession({
        _en_link("10"): _REJECTED,
    })

    with caplog.at_level("WARNING"):
        result = _scrape(session, "10", link_en=_en_link("10"), link_bm="")

    assert result is None
    assert any("not a detail page" in r.message for r in caplog.records)


def test_scrape_act_genuinely_empty_bm_page_still_recorded_absent():
    """A real detail page (carries the site wrapper) with no timeline entries
    is a genuine finding, distinct from a rejected/blocked response."""
    session = _FakeSession({
        _en_link("11"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT11-EN.pdf"),
        _bm_link("11"): _empty_detail_html(),
    })

    result = _scrape(session, "11", link_en=_en_link("11"), link_bm=_bm_link("11"))

    # Recorded, key present but empty — the fetch succeeded and genuinely
    # found no timeline. Unlike the rejected/transient case, this is final.
    assert "detail_url_bm" in result
    assert result["detail_url_bm"] == _bm_link("11")
    assert result["timeline_bm"] == []


def test_run_step2_backfill_retries_after_transient_bm_failure(tmp_path, monkeypatch):
    index = {"acts": [{"act_number": "8", "act_type": "updated", "title_en": "FIXTURE",
                        "title_link_en": _en_link("8"), "title_link_bm": _bm_link("8")}]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    old_format = {
        "act_number": "8",
        "act_type": "updated",
        "detail_url": _en_link("8"),
        "timeline": [{"date": "01/01/2018", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT8.pdf"}],
        "latest_reprint_pdf": "https://old/ACT8.pdf",
        "latest_amendment_pdf": "",
        "subsidiary_legislation": [],
        "subsidiary_total": 0,
    }
    (metadata_dir / "8.json").write_text(json.dumps(old_format), encoding="utf-8")

    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    flaky = _FlakySession({_bm_link("8"): _FlakySession.FAILS})
    monkeypatch.setattr("scraper.session.build_session", lambda: flaky)
    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "8.json").read_text(encoding="utf-8"))
    assert "detail_url_bm" not in saved

    # Once the page is reachable again, a later run backfills it instead of
    # having given up permanently.
    healthy = _FakeSession({_bm_link("8"): _detail_html("01/01/2018", "REPRINT ONLINE", "AKTA8.pdf")})
    monkeypatch.setattr("scraper.session.build_session", lambda: healthy)
    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "8.json").read_text(encoding="utf-8"))
    assert saved["detail_url_bm"] == _bm_link("8")


def test_run_step2_corrupt_metadata_file_does_not_abort_sweep(tmp_path, monkeypatch):
    index = {"acts": [
        {"act_number": "20", "act_type": "updated", "title_en": "CORRUPT FIXTURE",
         "title_link_en": _en_link("20"), "title_link_bm": _bm_link("20")},
        {"act_number": "21", "act_type": "updated", "title_en": "GOOD FIXTURE",
         "title_link_en": _en_link("21"), "title_link_bm": _bm_link("21")},
    ]}
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(tmp_path / "index.json"))

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    (metadata_dir / "20.json").write_text("{not valid json", encoding="utf-8")

    session = _FakeSession({
        _en_link("20"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT20-EN.pdf"),
        _bm_link("20"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT20-BM.pdf"),
        _en_link("21"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT21-EN.pdf"),
        _bm_link("21"): _detail_html("01/01/2020", "REPRINT ONLINE", "ACT21-BM.pdf"),
    })
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    step2_detail.run_step2()  # must not raise despite the corrupt file

    act20 = json.loads((metadata_dir / "20.json").read_text(encoding="utf-8"))
    act21 = json.loads((metadata_dir / "21.json").read_text(encoding="utf-8"))
    assert act20["latest_reprint_pdf"].endswith("ACT20-EN.pdf")
    assert act21["latest_reprint_pdf"].endswith("ACT21-EN.pdf")


def _index_file(tmp_path, monkeypatch, acts: list[dict]) -> Path:
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"acts": acts}), encoding="utf-8")
    monkeypatch.setattr(step2_detail, "INDEX_FILE", str(path))
    return path


def _metadata_dir_for(tmp_path, monkeypatch) -> Path:
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    monkeypatch.setattr(step2_detail, "METADATA_DIR", str(metadata_dir))
    return metadata_dir


def test_run_step2_refuses_an_index_written_before_signed_links(tmp_path, monkeypatch, caplog):
    """An index with no title_link_* keys says nothing about which languages
    exist. Running on it would stamp every Act confirmed-absent without a
    single request, so Step 2 must refuse instead."""
    _index_file(tmp_path, monkeypatch, [{"act_number": "9", "act_type": "updated", "title_en": "OLD INDEX"}])
    metadata_dir = _metadata_dir_for(tmp_path, monkeypatch)
    old_format = {
        "act_number": "9",
        "act_type": "updated",
        "detail_url": "https://lom.agc.gov.my/act-detail.php?act=9&lang=BI",
        "timeline": [{"date": "01/01/2018", "log_type": "REPRINT ONLINE", "pdf_url": "https://old/ACT9.pdf"}],
        "latest_reprint_pdf": "https://old/ACT9.pdf",
        "latest_amendment_pdf": "",
    }
    (metadata_dir / "9.json").write_text(json.dumps(old_format), encoding="utf-8")

    session = _FakeSession({})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    with caplog.at_level("ERROR"):
        step2_detail.run_step2()

    assert "re-run step 1" in caplog.text.lower()
    assert json.loads((metadata_dir / "9.json").read_text(encoding="utf-8")) == old_format
    assert step2_detail._needs_bm_backfill(old_format) is True


def test_run_step2_retries_a_previous_stub(tmp_path, monkeypatch):
    """A stub is a failed scrape, not a result — a stale token that works on a
    later run must be picked up automatically."""
    _index_file(tmp_path, monkeypatch, [
        {"act_number": "10", "act_type": "updated", "title_en": "STUB FIXTURE",
         "title_link_en": _en_link("10"), "title_link_bm": ""},
    ])
    metadata_dir = _metadata_dir_for(tmp_path, monkeypatch)
    (metadata_dir / "10.json").write_text(json.dumps({
        "act_number": "10", "act_type": "updated", "stub": True,
        "timeline": [], "latest_reprint_pdf": "", "latest_amendment_pdf": "",
        "subsidiary_legislation": [], "subsidiary_total": 0,
    }), encoding="utf-8")

    session = _FakeSession({_en_link("10"): _detail_html("01/01/2021", "REPRINT ONLINE", "ACT10-EN.pdf")})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    step2_detail.run_step2()

    saved = json.loads((metadata_dir / "10.json").read_text(encoding="utf-8"))
    assert "stub" not in saved
    assert saved["latest_reprint_pdf"].endswith("ACT10-EN.pdf")


def test_run_step2_refetches_the_key_when_agc_rotates_it_mid_sweep(tmp_path, monkeypatch):
    """A sweep runs for hours on one key. A rotation part-way through must not
    abort every remaining Act."""
    _index_file(tmp_path, monkeypatch, [
        {"act_number": "11", "act_type": "updated", "title_link_en": _en_link("11"), "title_link_bm": ""},
        {"act_number": "12", "act_type": "updated", "title_link_en": _en_link("12"), "title_link_bm": ""},
    ])
    metadata_dir = _metadata_dir_for(tmp_path, monkeypatch)

    rotated_key = "ab" * 32

    class _RotatingSession(_FakeSession):
        """Subsidiary POSTs stop decrypting under the old key after act 11."""

        def __init__(self, pages):
            super().__init__(pages)
            self.current_key = FAKE_RESPONSE_KEY
            self.posts = 0

        def post(self, url, data=None, timeout=None):
            self.posts += 1
            if self.posts > 1:
                self.current_key = rotated_key
            return _FakeResponse(200, json_body=encrypt_envelope({"recordsTotal": 0, "records": []},
                                                                key_hex=self.current_key))

    session = _RotatingSession({
        _en_link("11"): _detail_html("01/01/2021", "REPRINT ONLINE", "ACT11-EN.pdf"),
        _en_link("12"): _detail_html("01/01/2021", "REPRINT ONLINE", "ACT12-EN.pdf"),
    })
    monkeypatch.setattr("scraper.session.build_session", lambda: session)

    keys = iter([FAKE_RESPONSE_KEY, rotated_key])
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: next(keys))

    step2_detail.run_step2()

    assert json.loads((metadata_dir / "11.json").read_text(encoding="utf-8"))["latest_reprint_pdf"].endswith("ACT11-EN.pdf")
    saved12 = json.loads((metadata_dir / "12.json").read_text(encoding="utf-8"))
    assert "stub" not in saved12
    assert saved12["latest_reprint_pdf"].endswith("ACT12-EN.pdf")


def test_run_single_act_keeps_the_stub_when_the_rescrape_fails(tmp_path, monkeypatch):
    """A failed manual re-scrape must not drop the Act out of the metadata dir
    — it would vanish from the stub list too."""
    _index_file(tmp_path, monkeypatch, [
        {"act_number": "13", "act_type": "updated", "title_link_en": _en_link("13"), "title_link_bm": ""},
    ])
    metadata_dir = _metadata_dir_for(tmp_path, monkeypatch)
    stub = {
        "act_number": "13", "act_type": "updated", "stub": True,
        "timeline": [], "latest_reprint_pdf": "", "latest_amendment_pdf": "",
        "subsidiary_legislation": [], "subsidiary_total": 0,
    }
    (metadata_dir / "13.json").write_text(json.dumps(stub), encoding="utf-8")

    session = _FlakySession({_en_link("13"): _FlakySession.FAILS})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    step2_detail.run_single_act("13")

    assert json.loads((metadata_dir / "13.json").read_text(encoding="utf-8")) == stub


def test_run_single_act_refuses_an_index_written_before_signed_links(tmp_path, monkeypatch, caplog):
    _index_file(tmp_path, monkeypatch, [{"act_number": "14", "act_type": "updated"}])
    _metadata_dir_for(tmp_path, monkeypatch)

    session = _FakeSession({})
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    with caplog.at_level("ERROR"):
        step2_detail.run_single_act("14")

    assert "re-run step 1" in caplog.text.lower()
    assert session.requested == []


def test_run_step2_skips_an_act_whose_number_breaks_its_path(tmp_path, monkeypatch, caplog):
    """An act_number with a path separator makes every metadata path for it
    unwritable. That must cost one Act, not the rest of the sweep (#70)."""
    _index_file(tmp_path, monkeypatch, [
        {"act_number": "49/1965", "act_type": "updated",
         "title_link_en": _en_link("49-1965"), "title_link_bm": ""},
        {"act_number": "15", "act_type": "updated",
         "title_link_en": _en_link("15"), "title_link_bm": ""},
    ])
    metadata_dir = _metadata_dir_for(tmp_path, monkeypatch)

    session = _FakeSession({
        _en_link("49-1965"): _detail_html("01/01/2021", "REPRINT ONLINE", "ACT49-EN.pdf"),
        _en_link("15"): _detail_html("01/01/2021", "REPRINT ONLINE", "ACT15-EN.pdf"),
    })
    monkeypatch.setattr("scraper.session.build_session", lambda: session)
    monkeypatch.setattr(step2_detail, "fetch_response_key", lambda s: FAKE_RESPONSE_KEY)

    with caplog.at_level("ERROR"):
        step2_detail.run_step2()

    assert "49/1965" in caplog.text
    assert not (metadata_dir / "49").exists()
    # The Act behind the broken one still gets scraped.
    saved = json.loads((metadata_dir / "15.json").read_text(encoding="utf-8"))
    assert saved["latest_reprint_pdf"].endswith("ACT15-EN.pdf")
