"""
Decrypt AGC's AES-256-GCM encrypted listing responses.

Every json-*-2024.php endpoint now wraps its DataTables payload as
{"encrypted": true, "data": "<base64>"}. The base64 decodes to 12 bytes IV,
16 bytes GCM tag, then ciphertext — the same layout AGC's own
js/responseCrypto.js uses client-side. The key is a 64-hex-char constant
AGC prints as SEARCH_RESPONSE_KEY in principal.php; it is scraped at run
time, never hardcoded, since AGC can rotate it without notice.
"""
import base64
import json
import logging
import re
import time

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scraper.config import PRINCIPAL_URL, RETRY_DELAYS

logger = logging.getLogger(__name__)

_KEY_PATTERN = re.compile(r"SEARCH_RESPONSE_KEY\s*=\s*'([0-9a-fA-F]{64})'")


class DecryptionError(RuntimeError):
    """An encrypted envelope could not be decrypted.

    Callers must let this propagate rather than treating it as an empty
    result — a listing that fails to decrypt is a failure, not zero records.
    """


def extract_response_key(html: str) -> str:
    """Scrape the AES-256 key AGC embeds as SEARCH_RESPONSE_KEY in principal.php."""
    match = _KEY_PATTERN.search(html)
    if not match:
        raise DecryptionError("SEARCH_RESPONSE_KEY not found in principal.php")
    return match.group(1)


def fetch_response_key(session) -> str:
    """GET principal.php and scrape the AES key AGC embeds in the page.

    Shared by Step 1 (listings) and Step 2 (detail pages, subsidiary
    legislation) — every encrypted endpoint uses the same key. Never
    hardcoded: AGC can rotate it without notice, and a stale hardcoded key
    would make every fetch fail decryption as a corrupted-looking response
    instead of a clear "key changed" signal.
    """
    for attempt, wait in enumerate([0] + RETRY_DELAYS):
        if wait:
            logger.warning("Retrying %s after %ss (attempt %d)", PRINCIPAL_URL, wait, attempt)
            time.sleep(wait)
        try:
            resp = session.get(PRINCIPAL_URL, timeout=30)
            if resp.status_code == 200:
                return extract_response_key(resp.text)
            logger.warning("HTTP %s for %s", resp.status_code, PRINCIPAL_URL)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            logger.warning("Request error for %s: %s", PRINCIPAL_URL, exc)
    raise DecryptionError(f"Could not fetch response key from {PRINCIPAL_URL}")


def decrypt_envelope(envelope: dict, key_hex: str) -> dict:
    """Decrypt a {"encrypted": true, "data": "..."} response into its JSON payload."""
    if not isinstance(envelope, dict) or not envelope.get("encrypted"):
        raise DecryptionError(f"Response is not an encrypted envelope: {envelope!r:.200}")
    data = envelope.get("data")
    if not isinstance(data, str) or not data:
        raise DecryptionError("Encrypted envelope has no data")

    try:
        raw = base64.b64decode(data)
        if len(raw) < 28:
            raise DecryptionError("Encrypted payload shorter than IV+tag")
        iv, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        key = bytes.fromhex(key_hex)
        plaintext = AESGCM(key).decrypt(iv, ciphertext + tag, None)
        return json.loads(plaintext)
    except DecryptionError:
        raise
    except Exception as exc:
        raise DecryptionError(f"Failed to decrypt response: {exc}") from exc
