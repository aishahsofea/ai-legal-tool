"""
Step 3 — Download the canonical PDF for each Act.

For each act in data/acts_metadata/, tries in order:
  1. latest_reprint_pdf  — consolidated current text (preferred)
  2. latest_amendment_pdf — fallback for acts with no reprint
  3. skip                 — logged as no_pdf

Output: data/pdfs/en/{act_number}.pdf
Report: data/pdfs/download_report.json

Resumable: re-running skips acts that already have a PDF file.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from scraper.config import (
    METADATA_DIR,
    PDF_EN_DIR,
    DOWNLOAD_REPORT,
    REQUEST_DELAY,
    RETRY_DELAYS,
)

logger = logging.getLogger(__name__)


def _encode_url(url: str) -> str:
    """Encode spaces and special chars in AGC PDF URLs while preserving URL structure."""
    return quote(url, safe=':/?=&#@%+')


def _download_pdf(session: requests.Session, url: str, dest: Path, timeout: int = 120) -> bool:
    """Download one PDF to dest. Returns True on success."""
    encoded = _encode_url(url)
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying %s after %ss (attempt %d)", dest.name, wait, attempt)
            time.sleep(wait)
        try:
            resp = session.get(encoded, timeout=timeout, stream=True)
            if resp.status_code == 200:
                dest.write_bytes(resp.content)
                return True
            if resp.status_code == 404:
                logger.warning("404 — %s", encoded)
                return False
            if resp.status_code in (429, 503):
                backoff = 30 * (2 ** attempt)
                logger.warning("Rate limited (%s), sleeping %ss", resp.status_code, backoff)
                time.sleep(backoff)
            else:
                logger.warning("HTTP %s for %s", resp.status_code, encoded)
        except requests.exceptions.Timeout:
            logger.warning("Timeout for %s", dest.name)
            return False
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error for %s: %s", dest.name, exc)
    logger.error("Exhausted retries for %s", dest.name)
    return False


def _pick_url(meta: dict) -> tuple[str, str]:
    """Return (url, source) where source is 'reprint', 'amendment', or ''."""
    reprint = meta.get("latest_reprint_pdf", "")
    if reprint:
        return reprint, "reprint"
    amendment = meta.get("latest_amendment_pdf", "")
    if amendment:
        return amendment, "amendment"
    return "", ""


def run_step3() -> None:
    from scraper.session import build_download_session

    metadata_dir = Path(METADATA_DIR)
    out_dir = Path(PDF_EN_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_files = sorted(metadata_dir.glob("*.json"), key=lambda f: int(f.stem) if f.stem.isdigit() else 0)
    acts = []
    for f in meta_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not data.get("stub"):
            acts.append(data)

    logger.info("Step 3: %d acts to process", len(acts))

    session = build_download_session()

    downloaded = 0
    skipped_exists = 0
    skipped_no_url = 0
    failed = 0
    failures = []

    try:
        for i, meta in enumerate(acts, 1):
            act_number = meta["act_number"]
            dest = out_dir / f"{act_number}.pdf"

            if dest.exists():
                skipped_exists += 1
                continue

            url, source = _pick_url(meta)
            if not url:
                logger.info("[%d/%d] Act %s — no PDF URL, skipping", i, len(acts), act_number)
                skipped_no_url += 1
                continue

            title = meta.get("title_en", "")
            logger.info("[%d/%d] Act %s (%s) — downloading %s", i, len(acts), act_number, title[:50], source)

            ok = _download_pdf(session, url, dest)
            if ok:
                downloaded += 1
                logger.info("[%d/%d] Act %s — saved (%s)", i, len(acts), act_number, source)
            else:
                failed += 1
                failures.append({"act_number": act_number, "url": url, "source": source})
                logger.warning("Act %s — download failed", act_number)

            time.sleep(REQUEST_DELAY)

    except KeyboardInterrupt:
        logger.info("Interrupted. downloaded=%d skipped_exists=%d skipped_no_url=%d failed=%d",
                    downloaded, skipped_exists, skipped_no_url, failed)

    logger.info("Step 3 complete. downloaded=%d skipped_exists=%d skipped_no_url=%d failed=%d",
                downloaded, skipped_exists, skipped_no_url, failed)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "downloaded": downloaded,
        "skipped_exists": skipped_exists,
        "skipped_no_url": skipped_no_url,
        "failed": failed,
        "failures": failures,
    }
    report_path = Path(DOWNLOAD_REPORT)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report written to %s", DOWNLOAD_REPORT)
