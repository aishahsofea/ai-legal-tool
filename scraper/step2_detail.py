"""
Step 1.2 — Scrape act-detail pages and subsidiary legislation.

For each act in acts_index.json (updated + revised types by default):
  1. GET the Step 1-captured signed link for lang=EN → parse timeline
  2. GET the Step 1-captured signed link for lang=BM → parse timeline
  3. POST json-subsid-2024.php?act={number}          → subsidiary legislation

Since issue #64, act-detail.php no longer accepts a plain ?act=&lang=
query — every request goes through a signed processFile.php link that
Step 1 captured from the listing's title_link field. The listing already
says which languages exist for an Act, so EN and BM are fetched
independently and symmetrically: no more probing lang=BI first and falling
back to lang=BM only when it's entirely unavailable.

The primary fields (detail_url, timeline, latest_reprint_pdf,
latest_amendment_pdf) keep their existing meaning — English, or Malay when
English has no version at all for this Act — so a currently-registered
document's language never moves. A genuine second version lands in the
parallel *_bm fields instead.

Writes one file per act: data/acts_metadata/{act_number}.json

Resumable: skips acts whose output file already exists and already has the
*_bm fields. An existing file scraped before this variant existed gets its
missing lang=BM side backfilled in place, without re-fetching the primary
side (never risks moving an already-registered document's language). A stub
left by an earlier failed scrape is retried, not skipped.
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
from scraper.crypto import DecryptionError, decrypt_envelope, fetch_response_key
from scraper.parsers.detail_parser import parse_timeline, is_detail_page, find_latest_reprint, find_latest_amendment
from scraper.parsers.subsid_parser import parse_subsid_records

logger = logging.getLogger(__name__)


def _safe_get(session, url: str, timeout: int = 120) -> tuple[requests.Response | None, bool]:
    """GET with retries. Returns (response, definitely_absent).

    definitely_absent is True only for a real 404. Every other failure —
    timeout, connection error, retries exhausted — is transient, and callers
    that cache a "not found" result must not treat it as confirmation the
    page doesn't exist.
    """
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying GET %s after %ss", url, wait)
            time.sleep(wait)
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp, False
            if resp.status_code == 404:
                logger.warning("404 — %s", url)
                return None, True
            if resp.status_code in (429, 503):
                backoff = 30 * (2 ** attempt)
                logger.warning("Rate limited (%s), sleeping %ss", resp.status_code, backoff)
                time.sleep(backoff)
            else:
                logger.warning("HTTP %s for %s", resp.status_code, url)
        except requests.exceptions.Timeout:
            logger.warning("Timeout for %s — skipping", url)
            return None, False
        except requests.exceptions.ConnectionError as exc:
            logger.warning("Connection error for %s: %s", url, exc)
    logger.error("Exhausted retries for %s", url)
    return None, False


def _safe_post(session, url: str, payload: dict, key_hex: str) -> dict | None:
    """POST and decrypt the response envelope.

    A decryption failure propagates (not caught here) — same rule as Step 1:
    a subsidiary-legislation page that fails to decrypt is a failure, never
    an empty result.
    """
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying POST %s after %ss", url, wait)
            time.sleep(wait)
        try:
            resp = session.post(url, data=payload, timeout=120)
            if resp.status_code == 200:
                return decrypt_envelope(resp.json(), key_hex)
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


def fetch_subsidiary(session, act_number: str, key_hex: str) -> list[dict]:
    url = f"{SUBSID_URL}?act={act_number}"
    all_records: list[dict] = []
    start = 0
    draw = 1

    while True:
        payload = _build_dt_payload(draw=draw, start=start)
        data = _safe_post(session, url, payload, key_hex)

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


def _fetch_signed(session, url: str, timeout: int) -> str | None:
    """GET a Step 1-captured signed detail link, returning only a genuine
    detail-page render.

    Existence is decided by whether Step 1 captured a link at all (from the
    listing's title_link field), never by what this fetch returns — a token
    can go stale (issue #64), and AGC's 15-byte "Invalid request" rejection
    is indistinguishable from a blocked request. So any failure here —
    timeout, connection error, non-200, or a 200 that isn't a real detail
    page — is transient: callers must retry on a later run, never read it
    as "this Act has no such language".
    """
    resp, _ = _safe_get(session, url, timeout=timeout)
    if resp is None:
        return None
    if not is_detail_page(resp.text):
        logger.warning("Response for %s is not a detail page — treating as a transient failure", url)
        return None
    return resp.text


def scrape_act(
    session,
    act_number: str,
    act_type: str,
    key_hex: str,
    timeout: int = 120,
    html: str | None = None,
    link_en: str = "",
    link_bm: str = "",
) -> dict | None:
    """
    Scrape one act from its Step 1-captured signed detail links.

    link_en / link_bm are the processFile.php links Step 1 pulled from the
    listing's title_link field, or "" when that language has no detail page
    for this Act at all — the listing is the source of truth for which
    languages exist, so unlike before this doesn't probe lang=BI then fall
    back to lang=BM. Both languages are fetched independently.

    If html is provided, skip HTTP entirely and parse it as the English
    detail page (offline/manual recovery — no secondary fetch is attempted).
    """
    offline = html is not None
    if offline:
        en_url = f"{DETAIL_URL}?act={act_number}&lang=BI"
        en_html = html
        logger.info("[%s] Parsing from provided HTML", act_number)
    else:
        en_url = link_en
        en_html = _fetch_signed(session, link_en, timeout) if link_en else None
        if link_en:
            time.sleep(REQUEST_DELAY)

    bm_url = link_bm if not offline else ""
    bm_html = None
    if not offline and link_bm:
        bm_html = _fetch_signed(session, link_bm, timeout)
        time.sleep(REQUEST_DELAY)

    en_exists = offline or bool(link_en)
    bm_exists = (not offline) and bool(link_bm)

    if en_exists:
        if en_html is None:
            # English has a link per the listing but this fetch failed —
            # transient. Never fall back to Malay as if this Act were
            # Malay-only: that would move a registered document's language.
            return None
        primary_url, primary_timeline = en_url, parse_timeline(en_html)
    elif bm_exists:
        if bm_html is None:
            return None
        primary_url, primary_timeline = bm_url, parse_timeline(bm_html)
    else:
        logger.warning("[%s] No detail link for either language in the listing", act_number)
        return None

    if not primary_timeline:
        debug_html = en_html if en_exists else bm_html
        debug_path = Path(METADATA_DIR) / f"{act_number}_debug.html"
        debug_path.write_text(debug_html, encoding="utf-8")
        logger.warning("[%s] No timeline entries found — raw HTML saved to %s for inspection", act_number, debug_path)

    subsidiary = fetch_subsidiary(session, act_number, key_hex)

    result = {
        "act_number":           act_number,
        "act_type":             act_type,
        "scraped_at":           datetime.now(timezone.utc).isoformat(),
        "detail_url":           primary_url,
        "timeline":             primary_timeline,
        "latest_reprint_pdf":   find_latest_reprint(primary_timeline),
        "latest_amendment_pdf": find_latest_amendment(primary_timeline),
        "subsidiary_legislation": subsidiary,
        "subsidiary_total":     len(subsidiary),
    }

    if en_exists and bm_exists and bm_html is not None:
        bm_timeline = parse_timeline(bm_html)
        result["detail_url_bm"] = bm_url
        result["timeline_bm"] = bm_timeline
        result["latest_reprint_pdf_bm"] = find_latest_reprint(bm_timeline)
        result["latest_amendment_pdf_bm"] = find_latest_amendment(bm_timeline)
    elif en_exists and bm_exists:
        # bm_exists but the fetch failed transiently — omit the *_bm fields
        # entirely so _needs_bm_backfill retries this Act next run.
        pass
    else:
        # Either there's no separate Malay document for this Act (English
        # exists and Malay doesn't), or Malay was itself the primary
        # (English has no version at all) — either way there's no second
        # document. Confirmed-absent empty fields now, rather than leaving
        # them unset, so _needs_bm_backfill doesn't re-attempt this Act for
        # nothing on every future run.
        result["detail_url_bm"] = ""
        result["timeline_bm"] = []
        result["latest_reprint_pdf_bm"] = ""
        result["latest_amendment_pdf_bm"] = ""

    return result


def _needs_bm_backfill(existing: dict) -> bool:
    return not existing.get("stub") and "detail_url_bm" not in existing


def _index_predates_signed_links(acts: list[dict]) -> bool:
    """True when acts_index.json was written before Step 1 captured signed links.

    An empty title_link_bm means "AGC's listing has no Malay detail page" and
    is recorded as confirmed absent. A *missing* key means the index says
    nothing at all. Conflating the two would stamp every Act confirmed-absent
    without issuing a request, so Step 2 refuses to run on an old index
    instead.
    """
    return any("title_link_en" not in act and "title_link_bm" not in act for act in acts)


def _scrape_act_refreshing_key(session, key_hex: str, act: dict, **kwargs) -> tuple[dict | None, str]:
    """scrape_act, retried once with a freshly scraped key on DecryptionError.

    AGC rotates SEARCH_RESPONSE_KEY without notice and a full sweep runs for
    hours on one key, so a mid-run rotation would otherwise abort every
    remaining Act. Returns the key actually used, so the caller keeps the new
    one. A second failure still propagates — that is a real break, not a
    rotation.
    """
    args = (session, act["act_number"], act["act_type"])
    links = {"link_en": act.get("title_link_en", ""), "link_bm": act.get("title_link_bm", "")}
    try:
        return scrape_act(*args, key_hex, **links, **kwargs), key_hex
    except DecryptionError as exc:
        logger.warning("[%s] Decryption failed (%s) — refetching the response key", act["act_number"], exc)
        key_hex = fetch_response_key(session)
        return scrape_act(*args, key_hex, **links, **kwargs), key_hex


def backfill_bm_variant(
    session, act_number: str, existing: dict, link_bm: str = "", timeout: int = 120
) -> tuple[dict | None, bool]:
    """Add the lang=BM fields to an Act scraped before they existed.

    Never re-fetches or touches the existing primary fields (detail_url,
    timeline, latest_reprint_pdf, latest_amendment_pdf) — only the *_bm
    fields are added, so an already-registered document's language can't
    move.

    link_bm is the current listing's signed Malay link for this Act (empty
    when the listing has none). An empty link_bm is only authoritative on an
    index that carries the title_link_* keys at all — callers check that with
    _index_predates_signed_links first. Returns (merged_metadata, made_request).
    made_request is False when there is no separate Malay version to fetch
    at all — either the primary itself was already the lang=BM fallback (the
    pre-#64 BM-only shape), or the current listing carries no Malay link.
    merged_metadata is None when a request was made but failed transiently;
    the caller must not persist that as "no BM version" — retry later.
    """
    was_bm_fallback = "lang=bm" in str(existing.get("detail_url", "")).lower()
    if was_bm_fallback or not link_bm:
        merged = dict(existing)
        merged["detail_url_bm"] = ""
        merged["timeline_bm"] = []
        merged["latest_reprint_pdf_bm"] = ""
        merged["latest_amendment_pdf_bm"] = ""
        return merged, False

    bm_html = _fetch_signed(session, link_bm, timeout)
    if bm_html is None:
        return None, True
    bm_timeline = parse_timeline(bm_html)
    merged = dict(existing)
    merged["detail_url_bm"] = link_bm
    merged["timeline_bm"] = bm_timeline
    merged["latest_reprint_pdf_bm"] = find_latest_reprint(bm_timeline)
    merged["latest_amendment_pdf_bm"] = find_latest_amendment(bm_timeline)
    return merged, True


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
    if _index_predates_signed_links(acts):
        logger.error(
            "acts_index.json carries no title_link_en/title_link_bm — it was written "
            "before issue #64. Re-run step 1 first; running on it would record every "
            "Act as having no Malay version without fetching anything."
        )
        return
    logger.info("Step 2: %d acts to process (types: %s)", len(acts), detail_types)

    out_dir = Path(METADATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    key_hex = fetch_response_key(session)

    done = 0
    skipped = 0
    failed = 0
    backfilled = 0

    try:
        for i, act in enumerate(acts, 1):
            act_number = act["act_number"]
            out_file = out_dir / f"{act_number}.json"

            if out_file.exists():
                try:
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning("[%d/%d] Act %s — corrupt metadata file (%s), re-scraping", i, len(acts), act_number, exc)
                else:
                    if existing.get("stub"):
                        # A stub is a failed scrape, not a result — the signed
                        # token may just have gone stale mid-sweep. Fall through
                        # and retry instead of leaving it for a manual
                        # `run.py --act`.
                        logger.info("[%d/%d] Act %s — retrying previous stub", i, len(acts), act_number)
                    elif not _needs_bm_backfill(existing):
                        skipped += 1
                        continue
                    else:
                        logger.info("[%d/%d] Act %s — backfilling lang=BM", i, len(acts), act_number)
                        result, made_request = backfill_bm_variant(
                            session, act_number, existing, link_bm=act.get("title_link_bm", "")
                        )
                        if result is None:
                            logger.warning("[%d/%d] Act %s — lang=BM fetch failed, will retry next run", i, len(acts), act_number)
                            failed += 1
                        else:
                            out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                            backfilled += 1
                        # Pace only when a request was actually made — backfill_bm_variant
                        # skips the request entirely for BM-primary Acts.
                        if made_request:
                            time.sleep(REQUEST_DELAY)
                        continue

            logger.info("[%d/%d] Scraping act %s — %s", i, len(acts), act_number, act.get("title_en", ""))

            result, key_hex = _scrape_act_refreshing_key(session, key_hex, act)
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
        logger.info("Interrupted. Progress: done=%d skipped=%d backfilled=%d failed=%d", done, skipped, backfilled, failed)
        return

    logger.info("Step 2 complete. done=%d skipped=%d backfilled=%d failed=%d", done, skipped, backfilled, failed)

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
    An existing stub is left in place until a successful scrape overwrites it,
    so a failed attempt can't drop the Act out of the metadata dir (and out of
    the stub list) entirely.

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
    if html_path is None and _index_predates_signed_links([act]):
        logger.error(
            "Act %s has no title_link_en/title_link_bm — acts_index.json predates "
            "issue #64 and carries no signed detail link to fetch. Re-run step 1 first.",
            act_number,
        )
        return

    out_file = Path(METADATA_DIR) / f"{act_number}.json"
    if out_file.exists():
        existing = json.loads(out_file.read_text(encoding="utf-8"))
        if not existing.get("stub"):
            logger.info("Act %s already has complete data — delete the file manually to force re-scrape", act_number)
            return

    html = None
    if html_path:
        html = Path(html_path).read_text(encoding="utf-8")
        logger.info("Act %s — parsing from local file: %s", act_number, html_path)
    else:
        logger.info("Act %s — fetching with 300s timeout...", act_number)

    session = build_session()
    key_hex = fetch_response_key(session)
    result, _ = _scrape_act_refreshing_key(session, key_hex, act, timeout=300, html=html)

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
