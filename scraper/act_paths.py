"""The one mapping from an Act number to the filename its metadata lives under.

An Act number is whatever AGC publishes. Nearly all are digits, but the index
also carries '406 (Revised)', 'NO. 26 OF 1963' and '49/1965'. The last kind has
a path separator in it, so `data/acts_metadata/49/1965.json` points into a
directory that does not exist and the write fails (#70).

Every reader and writer of `data/acts_metadata/` derives the stem here.
`agent/nodes/citation_validator.py` is why this is one function rather than a
convention: it builds its path from an Act number that arrived in a citation,
never from a directory listing, so an escape that disagreed with Step 2's would
report every citation of an escaped Act as referencing an unknown Act — a wrong
answer given confidently, which is worse than the crash this replaces.

The escape is percent-style and reversible, and only touches characters that no
current Act number contains, so no existing metadata file is renamed.
"""
from __future__ import annotations

from pathlib import Path

# '%' is the escape marker, so it must be encoded first — before any other
# replacement introduces one. Decoding walks the same pairs in reverse.
_ESCAPES = (
    ("%", "%25"),
    ("/", "%2F"),
    ("\\", "%5C"),
)


def metadata_stem(act_number: str) -> str:
    """Filename stem for an Act, with no path separator left in it.

    Raises ValueError on an empty Act number, which has no file of its own and
    would otherwise write to a dotfile shared by every other empty one.
    """
    stem = str(act_number or "").strip()
    if not stem:
        raise ValueError("act_number is empty — it has no metadata filename")
    for raw, escaped in _ESCAPES:
        stem = stem.replace(raw, escaped)
    return stem


def act_number_from_stem(stem: str) -> str:
    """Inverse of metadata_stem, for callers that read the directory listing.

    `run.py --act` takes the published Act number, so anything that prints a
    filename back to a human or feeds one to that command has to decode first.
    """
    value = str(stem)
    for raw, escaped in reversed(_ESCAPES):
        value = value.replace(escaped, raw)
    return value


def metadata_path(root: str | Path, act_number: str, suffix: str = ".json") -> Path:
    return Path(root) / f"{metadata_stem(act_number)}{suffix}"
