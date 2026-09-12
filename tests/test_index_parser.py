import base64

from scraper.parsers.index_parser import (
    parse_revised_record,
    parse_title_link_html,
    parse_updated_record,
)


def _signed_href(inner_url: str, sig: str = "deadbeef") -> str:
    """Build a title_link anchor href the way AGC does: base64("<url>|<sig>")."""
    token = base64.b64encode(f"{inner_url}|{sig}".encode()).decode()
    return f"processFile.php?isDirect=1&token={token}"


def _title_link_html(act: str, date: str = "26-06-2026") -> str:
    bm_href = _signed_href(f"https://lom.agc.gov.my/act-detail.php?act={act}&lang=BM&date={date}#timeline")
    bi_href = _signed_href(f"https://lom.agc.gov.my/act-detail.php?act={act}&lang=BI&date={date}#timeline")
    return f'<a href="{bm_href}">Tajuk BM</a><a href="{bi_href}">Title EN</a>'


def test_parse_title_link_html_extracts_both_languages():
    html = _title_link_html("884")

    bm, en = parse_title_link_html(html)

    assert bm.startswith("https://lom.agc.gov.my/processFile.php")
    assert en.startswith("https://lom.agc.gov.my/processFile.php")
    assert bm != en


def test_parse_title_link_html_missing_language_is_empty():
    bi_only_href = _signed_href("https://lom.agc.gov.my/act-detail.php?act=144&lang=BI&date=01-01-2020#timeline")
    html = f'<a href="{bi_only_href}">Title EN</a>'

    bm, en = parse_title_link_html(html)

    assert bm == ""
    assert en.startswith("https://lom.agc.gov.my/processFile.php")


def test_parse_title_link_html_empty_input():
    assert parse_title_link_html("") == ("", "")


def test_parse_updated_record_includes_title_links():
    rec = {
        "lgt_act_no": "884",
        "title": '<a href="act-detail.php?act=884&lang=BM">BM</a><a href="act-detail.php?act=884&lang=BI">EN</a>',
        "title_link": _title_link_html("884"),
    }

    result = parse_updated_record(rec)

    assert result["title_link_bm"].startswith("https://lom.agc.gov.my/processFile.php")
    assert result["title_link_en"].startswith("https://lom.agc.gov.my/processFile.php")


def test_parse_revised_record_includes_title_links():
    rec = {
        "lgt_act_id": "883",
        "title": '<a href="act-detail.php?act=883&lang=BM">BM</a><a href="act-detail.php?act=883&lang=BI">EN</a>',
        "title_link": _title_link_html("883"),
        "lgt_timeline_date": "2026-06-15",
    }

    result = parse_revised_record(rec)

    assert result["title_link_bm"].startswith("https://lom.agc.gov.my/processFile.php")
    assert result["title_link_en"].startswith("https://lom.agc.gov.my/processFile.php")
