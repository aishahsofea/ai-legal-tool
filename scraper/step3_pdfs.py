"""
Step 3 — Download and immutably register the canonical PDF for each Act.

For each act in data/acts_metadata/, tries in order:
  1. latest_reprint_pdf  — consolidated current text (preferred)
  2. skip — amendments are never a base-Act fallback

Output: content-addressed data/pdfs/objects/sha256/... assets + manifest v2
Report: data/pdfs/download_report.json

Idempotent: re-running re-observes source bytes and deduplicates by immutable identity.
"""
import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from corpus.registration import register_pdf
from corpus.registry import CorpusRegistry
from corpus.manifest import source_language

from scraper.config import (
    METADATA_DIR,
    PDF_EN_DIR,
    DOWNLOAD_REPORT,
    REQUEST_DELAY,
    RETRY_DELAYS,
    INDEX_FILE,
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
                content_type = resp.headers.get("Content-Type", "").lower()
                if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
                    logger.warning("Unexpected content type %s for %s", content_type, encoded)
                    return False
                with dest.open("wb") as stream:
                    for block in resp.iter_content(1024 * 1024):
                        if block:
                            stream.write(block)
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
    """Return only a consolidated reprint; amendments never represent base Acts."""
    reprint = meta.get("latest_reprint_pdf", "")
    if reprint:
        return reprint, "reprint"
    return "", ""


def run_step3() -> None:
    from scraper.session import build_download_session

    metadata_dir = Path(METADATA_DIR)
    out_dir = Path(PDF_EN_DIR).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    index = json.loads(Path(INDEX_FILE).read_text(encoding="utf-8"))
    titles: dict[str, dict[str, str]] = {}
    for item in index.get("acts", []):
        act = str(item.get("act_number", ""))
        current = titles.setdefault(act, {"title_en": "", "title_bm": ""})
        for key in ("title_en", "title_bm"):
            if not current[key] and item.get(key):
                current[key] = str(item[key]).strip()

    meta_files = sorted(metadata_dir.glob("*.json"), key=lambda f: int(f.stem) if f.stem.isdigit() else 0)
    acts = []
    for f in meta_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not data.get("stub"):
            acts.append(data)

    logger.info("Step 3: %d acts to process", len(acts))

    session = build_download_session()

    downloaded = 0
    verified_unchanged = 0
    skipped_no_url = 0
    failed = 0
    failures = []

    try:
        known_documents = set(CorpusRegistry(manifest_path, asset_root=out_dir).documents)
    except Exception:
        known_documents = set()

    try:
        for i, meta in enumerate(acts, 1):
            act_number = meta["act_number"]
            url, source = _pick_url(meta)
            if not url:
                logger.info("[%d/%d] Act %s — no reprint PDF; amendment fallback prohibited", i, len(acts), act_number)
                skipped_no_url += 1
                continue

            language = source_language(meta, url)
            title = titles.get(act_number, {}).get(f"title_{language}", "")
            logger.info("[%d/%d] Act %s (%s) — downloading %s", i, len(acts), act_number, title[:50], source)

            staging = out_dir / "staging"
            staging.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=staging, suffix=".pdf", delete=False) as temp:
                temp_path = Path(temp.name)
            try:
                ok = _download_pdf(session, url, temp_path)
                if ok:
                    document = register_pdf(
                        temp_path, metadata=meta, act_title=title,
                        manifest_path=manifest_path, asset_root=out_dir,
                    )
                    if document.document_id in known_documents:
                        verified_unchanged += 1
                    else:
                        downloaded += 1
                        known_documents.add(document.document_id)
                    logger.info("[%d/%d] Act %s — registered %s", i, len(acts), act_number, document.document_id)
                else:
                    failed += 1
                    failures.append({"act_number": act_number, "url": url, "source": source})
                    logger.warning("Act %s — download failed", act_number)
            except Exception as exc:
                failed += 1
                failures.append({"act_number": act_number, "url": url, "source": source, "reason": str(exc)})
                logger.warning("Act %s — registration failed: %s", act_number, exc)
            finally:
                temp_path.unlink(missing_ok=True)

            time.sleep(REQUEST_DELAY)

    except KeyboardInterrupt:
        logger.info("Interrupted. downloaded=%d verified_unchanged=%d skipped_no_url=%d failed=%d",
                    downloaded, verified_unchanged, skipped_no_url, failed)

    logger.info("Step 3 complete. downloaded=%d verified_unchanged=%d skipped_no_url=%d failed=%d",
                downloaded, verified_unchanged, skipped_no_url, failed)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "downloaded": downloaded,
        "verified_unchanged": verified_unchanged,
        "skipped_no_url": skipped_no_url,
        "failed": failed,
        "failures": failures,
    }
    report_path = Path(DOWNLOAD_REPORT)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Report written to %s", DOWNLOAD_REPORT)
