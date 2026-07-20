"""Content-derived identities shared by scraping, extraction, and ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE_RE = re.compile(r"^[a-z][a-z0-9-]{1,15}$")


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def validate_sha256(value: str) -> str:
    digest = str(value).lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("SHA-256 must be 64 lowercase hexadecimal characters")
    return digest


def validate_language(value: str) -> str:
    language = str(value).lower()
    if not _LANGUAGE_RE.fullmatch(language):
        raise ValueError("language is not a safe corpus language identifier")
    return language


def document_id(act_number: object, language: str, digest: str) -> str:
    act = re.sub(r"[^a-z0-9]+", "-", str(act_number or "").strip().lower()).strip("-")
    if not act:
        raise ValueError("act_number is not safe for a corpus identity")
    return f"act-{act}-{validate_language(language)}-sha256-{validate_sha256(digest)}"


def extraction_id(document_identity: str, extractor: str, version: str, config_hash: str) -> str:
    seed = {
        "document_id": document_identity,
        "extractor": str(extractor),
        "extractor_version": str(version),
        "configuration_hash": validate_sha256(config_hash),
    }
    return f"extraction-sha256-{sha256_json(seed)}"


def asset_key(digest: str, suffix: str = ".pdf") -> str:
    digest = validate_sha256(digest)
    if suffix not in {".pdf", ".words.json.gz", ".chunks.json"}:
        raise ValueError("unsupported corpus asset suffix")
    return f"statutes/sha256/{digest[:2]}/{digest[2:4]}/{digest}{suffix}"


def validate_asset_key(value: str) -> str:
    key = str(value)
    path = PurePosixPath(key)
    if (
        not key
        or key.startswith("/")
        or "\\" in key
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != key
    ):
        raise ValueError("unsafe corpus asset key")
    return key


def content_hash(content: object) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def chunk_set_hash(chunks: Iterable[Mapping[str, object]]) -> str:
    stable = [
        {
            "act_number": str(chunk.get("act_number", "")),
            "section_number": str(chunk.get("section_number", "")),
            "content_sha256": str(chunk.get("content_sha256") or content_hash(chunk.get("content"))),
            "page_number": chunk.get("page_number"),
            "page_end": chunk.get("page_end") or chunk.get("page_number"),
            "language": str(chunk.get("language", "")),
        }
        for chunk in chunks
    ]
    return sha256_json(stable)
