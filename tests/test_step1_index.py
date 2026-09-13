import re
from pathlib import Path

import pytest

import scraper.step1_index as step1_index
from scraper.config import HOMEPAGE_URL
from scraper.crypto import DecryptionError
from tests.conftest import FAKE_RESPONSE_KEY, encrypt_envelope


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        return self._json_body


class _FakeSession:
    """Maps exact URLs to canned responses. Any unmapped URL 404s."""

    def __init__(self, pages: dict[str, _FakeResponse]):
        self._pages = pages
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return self._pages.get(url, _FakeResponse(404))

    def post(self, url, data=None, timeout=None):
        self.requested.append(url)
        return self._pages.get(url, _FakeResponse(404))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(step1_index.time, "sleep", lambda *_: None)


def _principal_html(key_hex: str = FAKE_RESPONSE_KEY) -> str:
    return f"<script>const SEARCH_RESPONSE_KEY = '{key_hex}';</script>"


def test_fetch_page_decrypts_envelope():
    url = "https://lom.agc.gov.my/json-updated-2024.php"
    envelope = encrypt_envelope({"recordsTotal": 1, "records": [{"lgt_act_no": "1"}]})
    session = _FakeSession({url: _FakeResponse(200, json_body=envelope)})

    data = step1_index._fetch_page(session, url, {}, FAKE_RESPONSE_KEY)

    assert data == {"recordsTotal": 1, "records": [{"lgt_act_no": "1"}]}


def test_fetch_page_404_returns_none():
    url = "https://lom.agc.gov.my/json-updated-2024.php"
    session = _FakeSession({url: _FakeResponse(404)})

    assert step1_index._fetch_page(session, url, {}, FAKE_RESPONSE_KEY) is None


def test_fetch_page_decrypt_failure_raises_not_empty():
    """A response that fails to decrypt must blow up the fetch, never be
    read as zero records — see issue #64's acceptance criteria."""
    url = "https://lom.agc.gov.my/json-updated-2024.php"
    session = _FakeSession({url: _FakeResponse(200, json_body={"encrypted": True, "data": "not-valid-base64-gcm"})})

    with pytest.raises(DecryptionError):
        step1_index._fetch_page(session, url, {}, FAKE_RESPONSE_KEY)


def test_fetch_page_wrong_key_raises():
    url = "https://lom.agc.gov.my/json-updated-2024.php"
    envelope = encrypt_envelope({"records": []})
    session = _FakeSession({url: _FakeResponse(200, json_body=envelope)})

    with pytest.raises(DecryptionError):
        step1_index._fetch_page(session, url, {}, "ff" * 32)


def test_fetch_all_records_paginates_and_parses(monkeypatch):
    url = step1_index.LISTING_ENDPOINTS["updated"]
    page1 = encrypt_envelope({
        "recordsTotal": 2,
        "records": [{"lgt_act_no": "1", "title": "<a href=\"x?lang=BI\">A</a>"}],
    })
    page2 = encrypt_envelope({
        "recordsTotal": 2,
        "records": [{"lgt_act_no": "2", "title": "<a href=\"x?lang=BI\">B</a>"}],
    })

    calls = {"n": 0}

    def fake_post(session_self, u, data=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(200, json_body=page1 if calls["n"] == 1 else page2)

    session = _FakeSession({})
    monkeypatch.setattr(_FakeSession, "post", fake_post)

    records = step1_index.fetch_all_records(session, "updated", FAKE_RESPONSE_KEY)

    assert [r["act_number"] for r in records] == ["1", "2"]


def test_run_step1_fetches_key_once_before_listings(tmp_path, monkeypatch):
    monkeypatch.setattr(step1_index, "INDEX_FILE", str(tmp_path / "index.json"))

    principal_hits = {"n": 0}
    envelope = encrypt_envelope({"recordsTotal": 0, "records": []})

    def fake_get(self, url, timeout=None):
        self.requested.append(url)
        if url == HOMEPAGE_URL:
            return _FakeResponse(200)
        if "principal.php" in url:
            principal_hits["n"] += 1
            return _FakeResponse(200, text=_principal_html())
        return _FakeResponse(404)

    def fake_post(self, url, data=None, timeout=None):
        self.requested.append(url)
        return _FakeResponse(200, json_body=envelope)

    monkeypatch.setattr(_FakeSession, "get", fake_get)
    monkeypatch.setattr(_FakeSession, "post", fake_post)
    monkeypatch.setattr("scraper.session.build_session", lambda: _FakeSession({}))

    step1_index.run_step1(types=["updated", "revised"])

    assert principal_hits["n"] == 1
    out = (tmp_path / "index.json").read_text(encoding="utf-8")
    assert '"acts": []' in out


def test_no_hardcoded_response_key_in_scraper_source():
    """Acceptance criterion (issue #64): the AES key must be scraped at run
    time, never committed as a literal."""
    scraper_dir = Path(__file__).resolve().parent.parent / "scraper"
    hex64 = re.compile(r"['\"][0-9a-fA-F]{64}['\"]")
    offenders = []
    for path in scraper_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if hex64.search(text):
            offenders.append(str(path))
    assert offenders == [], f"64-hex-char literal(s) found in: {offenders}"
