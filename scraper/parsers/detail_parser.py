"""
Parse the act-detail.php HTML page.

Extracts:
- Amendment timeline from li[data-date] elements
- PDF URL from iframe[data-src] inside each timeline entry
- The latest reprint/reprint-online PDF URL (the consolidated version)
"""
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup

BASE_URL = "https://lom.agc.gov.my"

# Log types that represent a consolidated version, in priority order
_REPRINT_TYPES = {"REPRINT ONLINE", "REPRINT"}


def _extract_pdf_url(raw: str) -> str:
    """
    The iframe src is a pdfjs viewer URL:
        pdfjs/web/viewer.html?file=../../../ilims/upload/.../Act56.pdf&embedded=true

    Extract and resolve the actual PDF path from the file= parameter.
    Returns an absolute URL, e.g.:
        https://lom.agc.gov.my/ilims/upload/.../Act56.pdf
    """
    if not raw:
        return ""
    # If it's already a direct PDF link, return as-is (with base URL if relative)
    if "viewer.html" not in raw:
        if raw.startswith("http"):
            return raw
        return f"{BASE_URL}/{raw.lstrip('/')}"

    parsed = urlparse(raw)
    file_param = parse_qs(parsed.query).get("file", [""])[0]
    if not file_param:
        return ""

    # Resolve the relative path: pdfjs/web/viewer.html?file=../../../ilims/...
    # Starting from /pdfjs/web/, three ../ steps bring us to the root
    # Simpler: just grab everything from "ilims/" onwards
    decoded = unquote(file_param)
    if "ilims/" in decoded:
        path = decoded[decoded.index("ilims/"):]
        return f"{BASE_URL}/{path}"

    return f"{BASE_URL}/{decoded.lstrip('../')}"


def parse_timeline(html: str) -> list[dict]:
    """
    Parse timeline entries from act-detail page HTML.

    The page has two separate lists:
      1. Navigation dots: <a data-date data-project-id data-log-type> — metadata only, no iframe
      2. Content panels: <li data-date> containing <iframe data-src> — PDF URL only, no log_type

    We build both, then join on date to produce complete entries.
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. Navigation dots → metadata
    nav = {}
    for a in soup.select("a[data-date]"):
        date = a.get("data-date", "")
        nav[date] = {
            "project_id": a.get("data-project-id", ""),
            "log_type":   a.get("data-log-type", "").upper().strip(),
        }

    # 2. Content panels → pdf_url
    panels = {}
    for li in soup.select("li[data-date]"):
        date = li.get("data-date", "")
        iframe = li.find("iframe")
        raw_src = iframe.get("data-src", "") if iframe else ""
        panels[date] = _extract_pdf_url(raw_src)

    # 3. Merge: use nav order as the canonical order
    events = []
    for date, meta in nav.items():
        events.append({
            "date":       date,
            "project_id": meta["project_id"],
            "log_type":   meta["log_type"],
            "pdf_url":    panels.get(date, ""),
        })

    return events


def find_latest_reprint(timeline: list[dict]) -> str:
    """
    Return the PDF URL of the most recent REPRINT ONLINE or REPRINT entry.
    Falls back to empty string if none exists.

    The legal source's labels are delivery formats, not a freshness ranking.
    Select across both labels by their strictly parsed DD/MM/YYYY date.  Entries
    with a missing or malformed date are deliberately ignored rather than being
    allowed to inherit the scrape order.
    """
    candidates: list[tuple[datetime, str]] = []
    for entry in timeline:
        if entry.get("log_type") not in _REPRINT_TYPES or not entry.get("pdf_url"):
            continue
        try:
            date = datetime.strptime(str(entry.get("date", "")), "%d/%m/%Y")
        except ValueError:
            continue
        candidates.append((date, entry["pdf_url"]))
    return max(candidates, default=(datetime.min, ""), key=lambda item: item[0])[1]


def find_latest_amendment(timeline: list[dict]) -> str:
    """Return the PDF URL of the most recent AMENDMENTS entry."""
    candidates = [e for e in timeline if e["log_type"] == "AMENDMENTS" and e["pdf_url"]]
    return candidates[-1]["pdf_url"] if candidates else ""
