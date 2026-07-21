"""Network-free operator CLI for the statutory reference graph."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .artifacts import apply_audit_decisions, candidate_dir, promote, read_decisions, write_candidate
from .audit import audit_report
from .build import build_graph
from .loader import connect_and_load, verify_database
from .models import GRAPH_DOCUMENT_ID
from .validation import validate_artifacts

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = ROOT / "data" / "reference_graph"


def _path(value: str) -> Path:
    return Path(value).resolve()


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline statutory reference graph")
    parser.add_argument("--root", default=str(DEFAULT_GRAPH_ROOT))
    parser.add_argument("--document-id", default=GRAPH_DOCUMENT_ID)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    validate = sub.add_parser("validate")
    validate.add_argument("--candidate", action="store_true")
    audit = sub.add_parser("audit")
    audit.add_argument("--decisions")
    sub.add_parser("promote")
    load = sub.add_parser("load")
    load.add_argument("--database-url")
    verify = sub.add_parser("verify-db")
    verify.add_argument("--database-url")
    args = parser.parse_args(argv)
    root = _path(args.root)
    if args.command == "build":
        document, provisions, edges, unresolved, candidates = build_graph(ROOT, args.document_id)
        target = write_candidate(root, document, provisions, edges, unresolved, candidates)
        _print({"status": "candidate_built", "directory": str(target), "provisions": len(provisions), "edges": len(edges),
                "unresolved": len(unresolved), "audit_candidates": len(candidates)})
        return 0
    if args.command == "validate":
        directory = candidate_dir(root, args.document_id) if args.candidate else root / args.document_id
        result = validate_artifacts(directory, require_promoted=not args.candidate)
        _print(result)
        return 0 if result["valid"] else 1
    if args.command == "audit":
        if args.decisions:
            apply_audit_decisions(root, args.document_id, read_decisions(_path(args.decisions)))
        _print(audit_report(root, args.document_id))
        return 0
    if args.command == "promote":
        _print({"status": "promoted", "directory": str(promote(root, args.document_id))})
        return 0
    database_url = args.database_url or os.getenv("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    if args.command == "load":
        _print({"status": "loaded", "counts": connect_and_load(database_url, root, args.document_id)})
        return 0
    import psycopg2
    connection = psycopg2.connect(database_url)
    try:
        _print({"status": "verified", "counts": verify_database(connection, args.document_id)})
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
