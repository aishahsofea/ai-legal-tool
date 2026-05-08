"""
Normalize raw DataTables records from each listing endpoint into a
canonical shape: {act_number, act_type, title_bm, title_en, ...extras}.
"""
from bs4 import BeautifulSoup


def parse_title_html(html: str) -> tuple[str, str]:
    """
    Extract BM and EN titles from the HTML-in-JSON title field.

    The HTML contains two anchors differentiated by lang=BM / lang=BI in href:
        <a href="act-detail.php?act=56&lang=BM&...">AKTA KETERANGAN 1950</a>
        <a href="act-detail.php?act=56&lang=BI&...">EVIDENCE ACT 1950</a>

    Returns (title_bm, title_en). Falls back to plain text if anchors not found.
    """
    soup = BeautifulSoup(html, "lxml")
    bm, bi = "", ""
    for a in soup.find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "lang=BM" in href:
            bm = text
        elif "lang=BI" in href:
            bi = text
    # Fallback: strip all tags and return as english title
    if not bm and not bi:
        bi = soup.get_text(separator=" ", strip=True)
    return bm, bi


def parse_updated_record(rec: dict) -> dict:
    bm, bi = parse_title_html(rec.get("title", ""))
    return {
        "act_number": rec["lgt_act_no"],
        "act_type":   "updated",
        "title_bm":   bm,
        "title_en":   bi,
    }


def parse_revised_record(rec: dict) -> dict:
    bm, bi = parse_title_html(rec.get("title", ""))
    return {
        "act_number":    rec["lgt_act_id"],
        "act_type":      "revised",
        "title_bm":      bm,
        "title_en":      bi,
        "revision_date": rec.get("lgt_timeline_date", ""),
    }


def parse_repealed_record(rec: dict) -> dict:
    return {
        "act_number":  rec["ILA_ACT_NO"],
        "act_type":    "repealed",
        "title_bm":    rec.get("TITLEBM", ""),
        "title_en":    rec.get("TITLEBI", ""),
        "repealed_by": rec.get("REPEALEDBY", ""),
    }


def parse_amendment_record(rec: dict) -> dict:
    return {
        "act_number":           rec["ACTNO_LEGISLATION"],  # e.g. "A1791"
        "act_type":             "amendment",
        "title_bm":             rec.get("TajukBM", ""),
        "title_en":             rec.get("TajukBI", ""),
        "publication_date":     rec.get("PUBLICATIONDATE", ""),
        "royal_assent_date":    rec.get("ROYALASSENTDATE", ""),
        "commencement_date_en": rec.get("COMMENCEMENTDATEBI", ""),
        "commencement_remark":  rec.get("COMMENCEMENTREMARKBI", ""),
        "project_id":           rec.get("ILP_PROJECT_ID", ""),
        "pdf_url_en":           rec.get("URLDOCBI", ""),
        "pdf_url_bm":           rec.get("URLDOCBM", ""),
    }


def parse_translated_record(rec: dict) -> dict:
    bm = BeautifulSoup(rec.get("titlebm", ""), "lxml").get_text(strip=True)
    bi = BeautifulSoup(rec.get("titlebi", ""), "lxml").get_text(strip=True)
    return {
        "act_number":            rec["lgt_act_id"],
        "act_type":              "translated",
        "title_bm":              bm,
        "title_en":              bi,
        "authoritative_language": rec.get("languageNaskhahSahih", ""),
    }


_PARSERS = {
    "updated":    parse_updated_record,
    "revised":    parse_revised_record,
    "repealed":   parse_repealed_record,
    "amendment":  parse_amendment_record,
    "translated": parse_translated_record,
}


def parse_record(act_type: str, rec: dict) -> dict:
    parser = _PARSERS.get(act_type)
    if parser is None:
        raise ValueError(f"Unknown act_type: {act_type!r}")
    return parser(rec)
