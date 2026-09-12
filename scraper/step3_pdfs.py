"""
Step 3 — Download and immutably register the canonical PDF for each Act.

For each act in data/acts_metadata/, downloads and registers a document for
every consolidated reprint it has:
  1. latest_reprint_pdf     — primary version (preferred; language derived
                               from the metadata's own URL/detail markers)
  2. latest_reprint_pdf_bm  — secondary version, when step 2 found one
  Amendments never represent base Acts, in either language.

An Act with only one reprint registers one document, exactly as before.

Output: content-addressed data/pdfs/objects/sha256/... assets + manifest v2
Report: data/pdfs/download_report.json

Idempotent: re-running re-observes source bytes and deduplicates by immutable identity.
"""
import json
import logging
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import requests

from corpus.registration import register_pdf
from corpus.registry import CorpusRegistry
from corpus.manifest import source_language, _timeline_for

from scraper.config import (
    METADATA_DIR,
    PDF_EN_DIR,
    DOWNLOAD_REPORT,
    DOWNLOAD_CONCURRENCY,
    RETRY_DELAYS,
    INDEX_FILE,
)

logger = logging.getLogger(__name__)


def _encode_url(url: str) -> str:
    """Encode spaces and special chars in AGC PDF URLs while preserving URL structure."""
    return quote(url, safe=':/?=&#@%+')


class _FetchOutcome(NamedTuple):
    ok: bool
    reason: str | None


class _DownloadTask(NamedTuple):
    meta: dict
    act_number: str
    url: str
    source: str
    language: str
    title: str
    explicit_language: str | None
    timeline_date: str | None
    timeline_type: str | None


class _Throttle:
    """Permit pool shared by the download workers.

    A ThreadPoolExecutor cannot be resized once built, so concurrency is bounded
    by how many permits exist rather than by how many threads do. A 429 or 503
    from any worker halves the permits for the rest of the run. They never grow
    back: the spike behind #52 showed 16 concurrent requests are survivable, not
    where the host's ceiling actually is.
    """

    def __init__(self, permits: int) -> None:
        self._limit = max(1, permits)
        self._in_flight = 0
        self._cond = threading.Condition()

    @contextmanager
    def slot(self):
        with self._cond:
            while self._in_flight >= self._limit:
                self._cond.wait()
            self._in_flight += 1
        try:
            yield
        finally:
            with self._cond:
                self._in_flight -= 1
                self._cond.notify()

    @property
    def limit(self) -> int:
        with self._cond:
            return self._limit

    def back_off(self) -> int:
        with self._cond:
            self._limit = max(1, self._limit // 2)
            self._cond.notify_all()
            return self._limit


def _download_pdf(
    session: requests.Session,
    url: str,
    dest: Path,
    timeout: int = 120,
    throttle: _Throttle | None = None,
) -> _FetchOutcome:
    """Download one PDF to dest.

    The reason is None on success and a short string on every failure path.
    run_step3 writes it into the report, where reason-less entries used to make
    a read timeout indistinguishable from a file that was never there.
    """
    encoded = _encode_url(url)
    slot = throttle.slot if throttle is not None else nullcontext
    last_status: int | None = None
    last_error: str | None = None

    for attempt, wait_seconds in enumerate([0] + RETRY_DELAYS):
        if wait_seconds:
            logger.warning("Retrying %s after %ss (attempt %d)", dest.name, wait_seconds, attempt)
            time.sleep(wait_seconds)

        backoff = 0
        try:
            with slot():
                resp = session.get(encoded, timeout=timeout, stream=True)
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if content_type and "pdf" not in content_type and "octet-stream" not in content_type:
                        logger.warning("Unexpected content type %s for %s", content_type, encoded)
                        return _FetchOutcome(False, f"unexpected content type: {content_type}")
                    with dest.open("wb") as stream:
                        for block in resp.iter_content(1024 * 1024):
                            if block:
                                stream.write(block)
                    return _FetchOutcome(True, None)

                if resp.status_code == 404:
                    logger.warning("404 — %s", encoded)
                    return _FetchOutcome(False, "404")

                # Checked before the 5xx branch below so a 503 is read as rate
                # limiting, not as one of this host's missing-file 500s.
                if resp.status_code in (429, 503):
                    limit = throttle.back_off() if throttle is not None else 0
                    backoff = 30 * (2 ** attempt)
                    last_status = resp.status_code
                    logger.warning("Rate limited (%s), concurrency now %d, sleeping %ss",
                                   resp.status_code, limit, backoff)
                else:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if 500 <= resp.status_code < 600 and content_type and "pdf" not in content_type:
                        # This host serves a missing file as 500 with an HTML
                        # body, so there is nothing here to come back for.
                        logger.warning("HTTP %s (%s) — permanent miss for %s",
                                       resp.status_code, content_type, encoded)
                        return _FetchOutcome(
                            False, f"permanent miss: HTTP {resp.status_code} ({content_type})"
                        )
                    last_status = resp.status_code
                    logger.warning("HTTP %s for %s", resp.status_code, encoded)
        except requests.exceptions.Timeout:
            last_error = "read timeout"
            logger.warning("Timeout for %s (attempt %d)", dest.name, attempt + 1)
        except requests.exceptions.ConnectionError as exc:
            last_error = f"connection error: {exc}"
            logger.warning("Connection error for %s: %s", dest.name, exc)

        # Slept outside the permit so a rate-limited worker is not holding a
        # slot the others are waiting on.
        if backoff:
            time.sleep(backoff)

    reason = last_error or (
        f"exhausted retries (last HTTP {last_status})" if last_status else "exhausted retries"
    )
    logger.error("Exhausted retries for %s: %s", dest.name, reason)
    return _FetchOutcome(False, reason)


def _pick_urls(meta: dict) -> list[tuple[str, str, str | None]]:
    """Return (url, source_label, explicit_language) for every consolidated
    reprint this Act has. Amendments never represent base Acts, in either
    language. The secondary (bm) language is explicit rather than inferred,
    since its URL alone may carry no lang=bm marker for source_language() to
    key off — step 2 already knows it came from the lang=BM detail page.
    """
    picks: list[tuple[str, str, str | None]] = []
    primary = meta.get("latest_reprint_pdf", "")
    if primary:
        picks.append((primary, "reprint", None))
    secondary = meta.get("latest_reprint_pdf_bm", "")
    if secondary and secondary != primary:
        picks.append((secondary, "reprint_bm", "bm"))
    return picks


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

    skipped_no_url = 0
    tasks: list[_DownloadTask] = []
    for i, meta in enumerate(acts, 1):
        act_number = meta["act_number"]
        picks = _pick_urls(meta)
        if not picks:
            logger.info("[%d/%d] Act %s — no reprint PDF; amendment fallback prohibited", i, len(acts), act_number)
            skipped_no_url += 1
            continue
        for url, source, explicit_language in picks:
            language = explicit_language or source_language(meta, url)
            timeline_key = "timeline_bm" if explicit_language else "timeline"
            timeline_date, timeline_type = _timeline_for(meta, url, key=timeline_key)
            tasks.append(_DownloadTask(
                meta=meta,
                act_number=act_number,
                url=url,
                source=source,
                language=language,
                title=titles.get(act_number, {}).get(f"title_{language}", ""),
                explicit_language=explicit_language,
                timeline_date=timeline_date,
                timeline_type=timeline_type,
            ))

    staging = out_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    throttle = _Throttle(DOWNLOAD_CONCURRENCY)
    worker_state = threading.local()
    sessions: list[requests.Session] = []
    staged: set[Path] = set()
    bookkeeping = threading.Lock()

    def _worker_session() -> requests.Session:
        # requests.Session is not thread-safe, so each worker builds its own
        # instead of sharing the single session this step used to create.
        session = getattr(worker_state, "session", None)
        if session is None:
            session = build_download_session()
            worker_state.session = session
            with bookkeeping:
                sessions.append(session)
        return session

    def _fetch(task: _DownloadTask) -> tuple[_DownloadTask, Path, _FetchOutcome]:
        with tempfile.NamedTemporaryFile(dir=staging, suffix=".pdf", delete=False) as temp:
            temp_path = Path(temp.name)
        with bookkeeping:
            staged.add(temp_path)
        try:
            outcome = _download_pdf(_worker_session(), task.url, temp_path, throttle=throttle)
        except Exception as exc:
            # One worker must not take the run down. The serial version recorded
            # an unexpected error against the Act and carried on; so does this.
            outcome = _FetchOutcome(False, f"{type(exc).__name__}: {exc}")
        return task, temp_path, outcome

    def _discard(temp_path: Path) -> None:
        temp_path.unlink(missing_ok=True)
        with bookkeeping:
            staged.discard(temp_path)

    downloaded = 0
    verified_unchanged = 0
    failed = 0
    failures = []

    try:
        known_documents = set(CorpusRegistry(manifest_path, asset_root=out_dir).documents)
    except Exception:
        known_documents = set()

    total = len(tasks)
    done = 0
    queued = iter(tasks)
    pending: set[Future] = set()
    executor = ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY, thread_name_prefix="step3-fetch")

    try:
        while True:
            # Only DOWNLOAD_CONCURRENCY fetched-but-unregistered PDFs exist at
            # once. Submitting all ~1200 up front would stage the whole corpus
            # (~1.2 GB) under data/pdfs/staging before registering any of it.
            while len(pending) < DOWNLOAD_CONCURRENCY:
                task = next(queued, None)
                if task is None:
                    break
                pending.add(executor.submit(_fetch, task))
            if not pending:
                break

            finished, pending = wait(pending, return_when=FIRST_COMPLETED)

            # Registration stays on this thread: the manifest write is serial
            # and the identity it assigns must not depend on fetch order.
            for future in finished:
                task, temp_path, outcome = future.result()
                done += 1
                try:
                    if not outcome.ok:
                        failed += 1
                        failures.append({
                            "act_number": task.act_number, "url": task.url,
                            "source": task.source, "reason": outcome.reason,
                        })
                        logger.warning("[%d/%d] Act %s — download failed: %s",
                                       done, total, task.act_number, outcome.reason)
                        continue
                    document = register_pdf(
                        temp_path, metadata=task.meta, act_title=task.title,
                        manifest_path=manifest_path, asset_root=out_dir,
                        source_url=task.url, language=task.language,
                        timeline_date=task.timeline_date, timeline_type=task.timeline_type,
                        detail_url=task.meta.get("detail_url_bm", "") if task.explicit_language else None,
                    )
                    if document.document_id in known_documents:
                        verified_unchanged += 1
                    else:
                        downloaded += 1
                        known_documents.add(document.document_id)
                    logger.info("[%d/%d] Act %s — registered %s",
                                done, total, task.act_number, document.document_id)
                except Exception as exc:
                    failed += 1
                    failures.append({
                        "act_number": task.act_number, "url": task.url,
                        "source": task.source, "reason": str(exc),
                    })
                    logger.warning("Act %s — registration failed: %s", task.act_number, exc)
                finally:
                    _discard(temp_path)

    except KeyboardInterrupt:
        logger.info("Interrupted. downloaded=%d verified_unchanged=%d skipped_no_url=%d failed=%d",
                    downloaded, verified_unchanged, skipped_no_url, failed)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        # A worker cancelled mid-fetch can still land a temp file after this
        # sweep; an orphan in staging is cheaper than blocking on a 120s read.
        with bookkeeping:
            leftovers, workers = list(staged), list(sessions)
        for temp_path in leftovers:
            temp_path.unlink(missing_ok=True)
        for session in workers:
            session.close()

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
