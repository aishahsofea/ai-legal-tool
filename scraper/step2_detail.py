"""
Step 1.2 — Scrape act-detail pages and subsidiary legislation.

For each act in acts_index.json (updated + revised types by default):
  1. GET act-detail.php?act={number}&lang=BI  → parse timeline
  2. POST json-subsid-2024.php?act={number}   → subsidiary legislation

Writes one file per act: data/acts_metadata/{act_number}.json

Resumable: skips acts whose output file already exists.
The HTTP cache (requests-cache) handles skipping already-fetched pages.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scraper.config import (
    DETAIL_URL,
    SUBSID_URL,
    FETCH_PAGE_SIZE,
    REQUEST_DELAY,
    RETRY_DELAYS,
    INDEX_FILE,
    METADATA_DIR,
)
from scraper.parsers.detail_parser import parse_timeline, find_latest_reprint, find_latest_amendment
from scraper.parsers.subsid_parser import parse_subsid_records

logger = logging.getLogger(__name__)


def _safe_get(session, url: str, timeout: int = 120) -> requests.Response | None:
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying GET %s after %ss", url, wait)
            time.sleep(wait)
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                logger.warning("404 — %s", url)
                return None
            if resp.status_code in (429, 503):
                backoff = 30 * (2 ** attempt)
                logger.warning("Rate limited (%s), sleeping %ss", resp.status_code, backoff)
                time.sleep(backoff)
            else:
                logger.warning("HTTP %s for %s", resp.status_code, url)
        except requests.exceptions.Timeout:
            logger.warning("Timeout for %s — skipping", url)
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error for %s: %s", url, exc)
    logger.error("Exhausted retries for %s", url)
    return None


def _safe_post(session, url: str, payload: dict) -> dict | None:
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying POST %s after %ss", url, wait)
            time.sleep(wait)
        try:
            resp = session.post(url, data=payload, timeout=120)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 503):
                backoff = 30 * (2 ** attempt)
                time.sleep(backoff)
            else:
                logger.warning("HTTP %s for POST %s", resp.status_code, url)
        except requests.exceptions.Timeout:
            logger.warning("Timeout for POST %s — skipping", url)
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error POST %s: %s", url, exc)
    return None


def _build_dt_payload(draw: int, start: int) -> dict:
    return {
        "draw":          str(draw),
        "start":         str(start),
        "length":        str(FETCH_PAGE_SIZE),
        "search[value]": "",
        "search[regex]": "false",
        "language":      "BI",
    }


def fetch_subsidiary(session, act_number: str) -> list[dict]:
    url = f"{SUBSID_URL}?act={act_number}"
    all_records: list[dict] = []
    start = 0
    draw = 1

    while True:
        payload = _build_dt_payload(draw=draw, start=start)
        data = _safe_post(session, url, payload)

        if data is None:
            break

        batch = data.get("data") or data.get("records") or []
        if not batch:
            break

        all_records.extend(batch)
        total = data.get("recordsTotal", 0)
        start += len(batch)
        draw += 1

        if start >= total:
            break

        time.sleep(REQUEST_DELAY)

    return parse_subsid_records(all_records)


def scrape_act(session, act_number: str, act_type: str, timeout: int = 120, html: str | None = None) -> dict | None:
    """
    Scrape one act. If html is provided, skip the HTTP fetch and parse that directly.
    Otherwise tries lang=BI first, falls back to lang=BM.
    """
    if html is not None:
        url = f"{DETAIL_URL}?act={act_number}&lang=BI"
        logger.info("[%s] Parsing from provided HTML", act_number)
    else:
        url = f"{DETAIL_URL}?act={act_number}&lang=BI"
        resp = _safe_get(session, url, timeout=timeout)
        if resp is None:
            logger.warning("[%s] lang=BI failed, trying lang=BM", act_number)
            url = f"{DETAIL_URL}?act={act_number}&lang=BM"
            resp = _safe_get(session, url, timeout=timeout)
        if resp is None:
            return None
        html = resp.text

    timeline = parse_timeline(html)
    if not timeline:
        debug_path = Path(METADATA_DIR) / f"{act_number}_debug.html"
        debug_path.write_text(html, encoding="utf-8")
        logger.warning("[%s] No timeline entries found — raw HTML saved to %s for inspection", act_number, debug_path)

    time.sleep(REQUEST_DELAY)

    subsidiary = fetch_subsidiary(session, act_number)

    return {
        "act_number":           act_number,
        "act_type":             act_type,
        "scraped_at":           datetime.now(timezone.utc).isoformat(),
        "detail_url":           url,
        "timeline":             timeline,
        "latest_reprint_pdf":   find_latest_reprint(timeline),
        "latest_amendment_pdf": find_latest_amendment(timeline),
        "subsidiary_legislation": subsidiary,
        "subsidiary_total":     len(subsidiary),
    }


def run_step2(detail_types: list[str] | None = None) -> None:
    from scraper.session import build_session

    if detail_types is None:
        detail_types = ["updated", "revised"]

    index_path = Path(INDEX_FILE)
    if not index_path.exists():
        logger.error("acts_index.json not found — run step 1 first")
        return

    index = json.loads(index_path.read_text(encoding="utf-8"))
    acts = [a for a in index["acts"] if a["act_type"] in detail_types]
    logger.info("Step 2: %d acts to process (types: %s)", len(acts), detail_types)

    out_dir = Path(METADATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()

    done = 0
    skipped = 0
    failed = 0

    try:
        for i, act in enumerate(acts, 1):
            act_number = act["act_number"]
            out_file = out_dir / f"{act_number}.json"

            if out_file.exists():
                skipped += 1
                continue

            logger.info("[%d/%d] Scraping act %s — %s", i, len(acts), act_number, act.get("title_en", ""))

            result = scrape_act(session, act_number, act["act_type"])
            if result is None:
                logger.warning("Failed to scrape act %s — writing stub so PDF download can proceed", act_number)
                result = {
                    "act_number": act_number,
                    "act_type":   act["act_type"],
                    "title_en":   act.get("title_en", ""),
                    "title_bm":   act.get("title_bm", ""),
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "stub":       True,
                    "timeline":             [],
                    "latest_reprint_pdf":   "",
                    "latest_amendment_pdf": "",
                    "subsidiary_legislation": [],
                    "subsidiary_total":     0,
                }
                failed += 1

            out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            done += 1
            time.sleep(REQUEST_DELAY)

    except KeyboardInterrupt:
        logger.info("Interrupted. Progress: done=%d skipped=%d failed=%d", done, skipped, failed)
        return

    logger.info("Step 2 complete. done=%d skipped=%d failed=%d", done, skipped, failed)

    # Print stub list at the end so the user knows what needs manual re-scraping
    stubs = [f.stem for f in Path(METADATA_DIR).glob("*.json")
             if json.loads(f.read_text()).get("stub")]
    if stubs:
        logger.info("Stubs needing manual re-scrape (%d): %s", len(stubs), ", ".join(sorted(stubs, key=lambda x: int(x) if x.isdigit() else x)))


def list_stubs() -> None:
    """Print all acts that are stubs (detail page failed to load)."""
    stubs = []
    for f in sorted(Path(METADATA_DIR).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("stub"):
            stubs.append((f.stem, data.get("title_en", "")))

    if not stubs:
        print("No stubs found — all acts scraped successfully.")
        return

    print(f"{len(stubs)} stub(s) need manual re-scraping:\n")
    for act_number, title in stubs:
        print(f"  python run.py --act {act_number}   # {title}")


def run_single_act(act_number: str, html_path: str | None = None) -> None:
    """
    Manually re-scrape one act with a longer timeout (5 minutes).
    Deletes the existing stub file first so it gets replaced with real data.

    If html_path is given, parse that file instead of making an HTTP request —
    useful for acts whose page loads in a browser but times out in the scraper.
    """
    from scraper.session import build_session

    index_path = Path(INDEX_FILE)
    if not index_path.exists():
        logger.error("acts_index.json not found — run step 1 first")
        return

    index = json.loads(index_path.read_text(encoding="utf-8"))
    act = next((a for a in index["acts"] if a["act_number"] == act_number), None)
    if act is None:
        logger.error("Act %s not found in acts_index.json", act_number)
        return

    out_file = Path(METADATA_DIR) / f"{act_number}.json"
    if out_file.exists():
        existing = json.loads(out_file.read_text(encoding="utf-8"))
        if not existing.get("stub"):
            logger.info("Act %s already has complete data — delete the file manually to force re-scrape", act_number)
            return
        out_file.unlink()

    html = None
    if html_path:
        html = Path(html_path).read_text(encoding="utf-8")
        logger.info("Act %s — parsing from local file: %s", act_number, html_path)
    else:
        logger.info("Act %s — fetching with 300s timeout...", act_number)

    session = build_session()
    result = scrape_act(session, act_number, act["act_type"], timeout=300, html=html)

    if result is None:
        logger.error(
            "Act %s still failed. Load the page in your browser, then save the page source and run:\n"
            "  python run.py --act %s --html /path/to/saved.html",
            act_number, act_number,
        )
        return

    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Act %s scraped successfully — %d timeline entries, %d subsidiary",
                act_number, len(result["timeline"]), result["subsidiary_total"])
