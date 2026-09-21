"""Reproducible split of currency-check outcomes across the indexed corpus.

Walks data/pdfs/manifest.json's active_documents -- the act/language mapping
retrieval actually serves -- and classifies each one with the same helpers
agent/nodes/currency_check.py uses at query time, so this script and the
runtime can never silently drift apart (#60).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from agent.citation_keys import canonicalize_act_number
from agent.nodes.currency_check import _label_for_act, _reprint_dates_by_document

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = ROOT / "data" / "pdfs" / "manifest.json"

_LABELS = ("repealed", "superseded", "current_as_indexed", "unknown")


def split(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reprint_dates = _reprint_dates_by_document(manifest_path)

    counts: Counter[str] = Counter()
    documents: dict[str, list[dict[str, str]]] = {label: [] for label in _LABELS}

    for entry in manifest.get("active_documents", []):
        act_number = str(entry.get("act_number", ""))
        canonical_act = canonicalize_act_number(act_number)
        if not canonical_act:
            continue

        language = str(entry.get("language", "en"))
        document_id = str(entry.get("document_id", ""))
        reprint_date = reprint_dates.get(document_id, "")

        label = _label_for_act(act_number, canonical_act, language, reprint_date)
        counts[label["label"]] += 1
        documents[label["label"]].append({
            "act_number": act_number,
            "language": language,
            "document_id": document_id,
            "as_of_date": label["as_of_date"],
        })

    return {"counts": {label: counts.get(label, 0) for label in _LABELS}, "documents": documents}


def _print_report(report: dict[str, Any]) -> None:
    counts = report["counts"]
    total = sum(counts.values())
    print(f"\nCurrency check split ({total} active documents)")
    for label in _LABELS:
        print(f"  {label:<20} {counts[label]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Split the indexed corpus by currency-check outcome.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=None, help="Write the full per-document report as JSON.")
    args = parser.parse_args()

    report = split(args.manifest)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
