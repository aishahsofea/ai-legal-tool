"""Network-free operator CLI for the statutory reference graph."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .artifacts import (
    apply_audit_decisions,
    artifact_hashes,
    candidate_dir,
    promote,
    read_decisions,
    write_candidate,
)
from .audit import audit_report, decision_template
from .build import build_graph
from .loader import apply_migrations, connect_and_load, verify_database
from .models import DEFAULT_GRAPH_DOCUMENT_ID
from .snapshots import acquire_snapshots, catalog_report, catalog_snapshots, write_report
from .validation import validate_artifacts

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH_ROOT = ROOT / "data" / "reference_graph"
DEFAULT_MANIFEST = ROOT / "data" / "pdfs" / "manifest.json"
DEFAULT_ASSET_ROOT = ROOT / "data" / "pdfs"
DEFAULT_METADATA = ROOT / "data" / "acts_metadata" / "265.json"
DEFAULT_STAGING_ROOT = ROOT / "data" / "pdfs" / ".downloads" / "reference-graph"
DEFAULT_ACQUISITION_REPORT = DEFAULT_GRAPH_ROOT / "snapshot-acquisition-act-265.json"


def _path(value: str) -> Path:
    return Path(value).resolve()


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline statutory reference graph")
    parser.add_argument("--root", default=str(DEFAULT_GRAPH_ROOT))
    parser.add_argument("--document-id", default=DEFAULT_GRAPH_DOCUMENT_ID)
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog")
    catalog.add_argument("--metadata", default=str(DEFAULT_METADATA))
    catalog.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    catalog.add_argument("--asset-root", default=str(DEFAULT_ASSET_ROOT))
    catalog.add_argument("--report")
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--metadata", default=str(DEFAULT_METADATA))
    acquire.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    acquire.add_argument("--asset-root", default=str(DEFAULT_ASSET_ROOT))
    acquire.add_argument("--staging-root", default=str(DEFAULT_STAGING_ROOT))
    acquire.add_argument("--report", default=str(DEFAULT_ACQUISITION_REPORT))
    acquire.add_argument("--snapshot-date", action="append", default=[])
    acquire.add_argument("--all", action="store_true")
    acquire.add_argument(
        "--download",
        action="store_true",
        help="Explicitly permit network download and immutable registration.",
    )
    sub.add_parser("build")
    sub.add_parser("verify-determinism")
    validate = sub.add_parser("validate")
    validate.add_argument("--candidate", action="store_true")
    audit = sub.add_parser("audit")
    audit_input = audit.add_mutually_exclusive_group()
    audit_input.add_argument("--decisions")
    audit_input.add_argument("--export-decisions")
    sub.add_parser("promote")
    load = sub.add_parser("load")
    load.add_argument("--database-url")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--database-url")
    verify = sub.add_parser("verify-db")
    verify.add_argument("--database-url")
    args = parser.parse_args(argv)
    root = _path(args.root)
    if args.command in {"catalog", "acquire"}:
        metadata = _path(args.metadata)
        manifest = _path(args.manifest)
        asset_root = _path(args.asset_root)
        entries = catalog_snapshots(metadata, manifest, asset_root=asset_root)
        if args.command == "catalog" or not args.download:
            report = catalog_report(entries)
            if getattr(args, "report", None):
                write_report(_path(args.report), report)
            _print(report)
            return 0
        if not args.all and not args.snapshot_date:
            raise SystemExit("acquire --download requires --all or at least one --snapshot-date YYYY-MM-DD")
        available_dates = {entry.snapshot_date for entry in entries}
        selected_dates = available_dates if args.all else set(args.snapshot_date)
        unknown = selected_dates - available_dates
        if unknown:
            raise SystemExit(f"unknown snapshot date(s): {', '.join(sorted(unknown))}")
        from corpus.registry import CorpusRegistry
        registry = CorpusRegistry(manifest, asset_root=asset_root)
        titles = {
            document.act_title
            for document in registry.versions_for_act(entries[0].act_number, entries[0].language)
            if document.act_title
        }
        if not titles:
            raise SystemExit("an existing registered Act title is required for snapshot registration")
        report = acquire_snapshots(
            entries,
            metadata_path=metadata,
            manifest_path=manifest,
            asset_root=asset_root,
            staging_root=_path(args.staging_root),
            act_title=sorted(titles)[0],
            selected_dates=selected_dates,
        )
        write_report(_path(args.report), report)
        _print(report)
        return 0
    if args.command == "build":
        report_path = candidate_dir(root, args.document_id) / "build-report.json"
        try:
            document, provisions, edges, unresolved, candidates = build_graph(ROOT, args.document_id)
            target = write_candidate(root, document, provisions, edges, unresolved, candidates)
            report = {
                "status": "candidate_built",
                "document_id": args.document_id,
                "directory": str(target),
                "provisions": len(provisions),
                "edges": len(edges),
                "unresolved": len(unresolved),
                "audit_candidates": len(candidates),
                "artifact_hashes": artifact_hashes(target),
            }
        except Exception as exc:
            report = {
                "status": "blocked",
                "document_id": args.document_id,
                "stage": "registered_pdf_parse",
                "reason": str(exc) or type(exc).__name__,
                "error_class": type(exc).__name__,
            }
            write_report(report_path, report)
            _print(report)
            return 1
        write_report(report_path, report)
        _print(report)
        return 0
    if args.command == "verify-determinism":
        hashes = []
        with tempfile.TemporaryDirectory(prefix="reference-graph-determinism-") as temporary:
            for run in ("first", "second"):
                document, provisions, edges, unresolved, candidates = build_graph(ROOT, args.document_id)
                directory = write_candidate(
                    Path(temporary) / run,
                    document,
                    provisions,
                    edges,
                    unresolved,
                    candidates,
                )
                hashes.append(artifact_hashes(directory))
        identical = hashes[0] == hashes[1]
        _print({
            "status": "deterministic" if identical else "non_deterministic",
            "document_id": args.document_id,
            "identical": identical,
            "artifact_hashes": hashes[0] if identical else hashes,
        })
        return 0 if identical else 1
    if args.command == "validate":
        directory = candidate_dir(root, args.document_id) if args.candidate else root / args.document_id
        result = validate_artifacts(directory, require_promoted=not args.candidate)
        _print(result)
        return 0 if result["valid"] else 1
    if args.command == "audit":
        if args.export_decisions:
            destination = write_report(
                _path(args.export_decisions),
                decision_template(root, args.document_id),
            )
            _print({
                "status": "decision_template_exported",
                "document_id": args.document_id,
                "path": str(destination),
            })
            return 0
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
        if args.command == "migrate":
            _print({"status": "migrated", "migrations": apply_migrations(connection)})
            return 0
        result = verify_database(connection, args.document_id, root=root)
        _print({"status": "verified" if result["valid"] else "verification_failed", **result})
        return 0 if result["valid"] else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
