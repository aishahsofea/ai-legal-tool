import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Force the in-process MemorySaver checkpointer for the whole test suite so that
# importing agent.graph never opens a real Postgres connection (DATABASE_URL is
# present in .env and is loaded by node modules at import time).
os.environ.setdefault("CHECKPOINTER", "memory")

# A fixture-only AES-256 key (never AGC's real one) shared by the scraper
# crypto/step1/step2 tests that need to build a realistic encrypted envelope.
FAKE_RESPONSE_KEY = "00" * 32


def encrypt_envelope(payload: dict, key_hex: str = FAKE_RESPONSE_KEY) -> dict:
    """Build a {"encrypted": true, "data": ...} envelope like AGC's endpoints
    return, using the same 12-byte-IV + 16-byte-tag + ciphertext layout as
    js/responseCrypto.js (see scraper/crypto.py)."""
    key = bytes.fromhex(key_hex)
    iv = b"\x00" * 12
    plaintext = json.dumps(payload).encode("utf-8")
    ciphertext_with_tag = AESGCM(key).encrypt(iv, plaintext, None)
    ciphertext, tag = ciphertext_with_tag[:-16], ciphertext_with_tag[-16:]
    raw = iv + tag + ciphertext
    return {"encrypted": True, "data": base64.b64encode(raw).decode("ascii")}
