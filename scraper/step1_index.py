"""
Step 1.1 — Scrape all listing endpoints and write acts_index.json.

Each listing endpoint is a DataTables server-side API. We POST with
start/length pagination and collect all records.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from scraper.config import (
    LISTING_ENDPOINTS,
    FETCH_PAGE_SIZE,
    REQUEST_DELAY,
    RETRY_DELAYS,
    INDEX_FILE,
)
from scraper.parsers.index_parser import parse_record

logger = logging.getLogger(__name__)


def _build_payload(draw: int, start: int, length: int = FETCH_PAGE_SIZE) -> dict:
    return {
        "draw":           str(draw),
        "start":          str(start),
        "length":         str(length),
        "search[value]":  "",
        "search[regex]":  "false",
        "language":       "BI",
        "searchValue":    "",
    }


def _fetch_page(session, url: str, payload: dict) -> dict | None:
    """POST one DataTables page. Returns parsed JSON or None on unrecoverable error."""
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying %s after %ss (attempt %d)", url, wait, attempt)
            time.sleep(wait)
        try:
            resp = session.post(url, data=payload, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                logger.error("404 for %s — skipping", url)
                return None
            logger.warning("HTTP %s for %s", resp.status_code, url)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            logger.warning("Request error for %s: %s", url, exc)
    logger.error("Exhausted retries for %s", url)
    return None


def fetch_all_records(session, act_type: str) -> list[dict]:
    """Fetch every record for one act type via paginated POST calls."""
    url = LISTING_ENDPOINTS[act_type]
    records = []
    start = 0
    draw = 1
    total = None

    while True:
        payload = _build_payload(draw=draw, start=start)
        data = _fetch_page(session, url, payload)

        if data is None:
            logger.error("[%s] Failed to fetch page start=%d — stopping", act_type, start)
            break

        if total is None:
            total = data.get("recordsTotal", 0)
            logger.info("[%s] Total records: %d", act_type, total)

        batch = data.get("data") or data.get("records") or []
        if not batch:
            logger.info("[%s] Empty batch at start=%d — done", act_type, start)
            break

        for raw in batch:
            try:
                records.append(parse_record(act_type, raw))
            except (KeyError, ValueError) as exc:
                logger.warning("[%s] Parse error on record: %s — %s", act_type, raw, exc)

        logger.info("[%s] Fetched %d / %d", act_type, len(records), total)
        start += len(batch)
        draw += 1

        if start >= total:
            break

        time.sleep(REQUEST_DELAY)

    return records


def run_step1(types: list[str] | None = None) -> None:
    from scraper.session import build_session

    if types is None:
        types = list(LISTING_ENDPOINTS.keys())

    session = build_session()

    # Warm up session with a homepage hit
    try:
        session.get("https://lom.agc.gov.my/", timeout=15)
        time.sleep(REQUEST_DELAY)
    except Exception as exc:
        logger.warning("Homepage warmup failed: %s", exc)

    all_acts: list[dict] = []
    totals: dict[str, int] = {}

    for act_type in types:
        logger.info("=== Fetching type: %s ===", act_type)
        records = fetch_all_records(session, act_type)
        totals[act_type] = len(records)
        all_acts.extend(records)
        logger.info("[%s] Done — %d records", act_type, len(records))
        time.sleep(REQUEST_DELAY)

    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "totals":     totals,
        "acts":       all_acts,
    }

    out_path = Path(INDEX_FILE)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %d total acts to %s", len(all_acts), INDEX_FILE)
