"""Operator CLI for deterministic corpus lifecycle operations."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Sequence

import psycopg2
from dotenv import load_dotenv

from agent.embeddings import corpus_embedding_model, embedding_client
from corpus.db import (
    MIGRATION_PATH,
    activate,
    apply_migration,
    ingest_extraction,
    load_bundle,
    register_document,
    register_extraction,
    register_source_observation,
    rollback,
)
from corpus.extraction import diff_extraction_manifests, extract_manifest
from corpus.manifest import dump_json, generate_manifest
from corpus.registry import CorpusRegistry
from corpus.rollout import rollout_corpus
from corpus.validation import validate_manifest

load_dotenv()


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _database_url(value: str | None) -> str:
    url = value or os.getenv("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL or --database-url is required")
    return url


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _generate(args: argparse.Namespace) -> int:
    manifest, report = generate_manifest(
        pdf_root=_path(args.pdf_root),
        metadata_root=_path(args.metadata_root),
        index_path=_path(args.index),
        chunks_root=_path(args.chunks_root) if args.chunks_root else None,
        existing_manifest=_path(args.existing_manifest) if args.existing_manifest else None,
        extract_report=_path(args.extract_report) if args.extract_report else None,
    )
    dump_json(_path(args.output), manifest)
    dump_json(_path(args.report), report)
    _print({
        "manifest": _path(args.output).as_posix(),
        "report": _path(args.report).as_posix(),
        "documents": len(manifest["documents"]),
        "coverage": {key: report[key] for key in (
            "input_pdf_count", "enabled_pdf_count", "ready_pdf_count", "blocked_pdf_count"
        )},
    })
    return 0


def _validate(args: argparse.Namespace) -> int:
    result = validate_manifest(
        _path(args.manifest),
        asset_root=_path(args.pdf_root) if args.pdf_root else None,
        sidecar_root=_path(args.sidecar_root) if args.sidecar_root else None,
        cdn_base_url=args.cdn_base_url or None,
        scope=args.scope,
        deep=args.deep,
    )
    if args.format == "json":
        _print(result)
    else:
        print(
            f"valid={result['valid']} documents={result['document_count']} "
            f"extractions={result['extraction_count']} active={result['active_count']}"
        )
        for error in result["errors"]:
            print(f"- {error['code']}: {error.get('document_id', '')} {error['detail']}")
        for warning in result.get("warnings", []):
            print(f"! {warning['code']}: {warning['detail']}")
    return 0 if result["valid"] else 1


def _shadow(args: argparse.Namespace) -> int:
    registry = CorpusRegistry(
        _path(args.manifest),
        asset_root=_path(args.pdf_root) if args.pdf_root else None,
        sidecar_root=_path(args.sidecar_root),
    )
    manifest, report = extract_manifest(
        registry,
        extraction_root=_path(args.extraction_root),
        sidecar_root=_path(args.sidecar_root),
        document_ids=args.document_id or None,
        activate_ready=args.activate_ready,
    )
    dump_json(_path(args.output or args.manifest), manifest)
    dump_json(_path(args.report), report)
    _print({"ready": report["ready"], "blocked": report["blocked"], "report": _path(args.report).as_posix()})
    return 0 if not report["blocked"] else 2


def _diff_extractions(args: argparse.Namespace) -> int:
    old_manifest = json.loads(_path(args.old_manifest).read_text(encoding="utf-8"))
    new_manifest = json.loads(_path(args.new_manifest).read_text(encoding="utf-8"))
    diffs = diff_extraction_manifests(
        old_manifest,
        new_manifest,
        old_extraction_root=_path(args.old_extraction_root),
        new_extraction_root=_path(args.new_extraction_root),
        document_ids=args.document_id or None,
    )
    if args.format == "json":
        _print(diffs)
        return 0
    changed = {document_id: diff for document_id, diff in diffs.items() if diff["added"] or diff["removed"] or diff["changed"]}
    print(f"{len(changed)} of {len(diffs)} compared documents changed")
    for document_id, diff in sorted(changed.items()):
        print(f"- {document_id}: +{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['changed'])}")
        for entry in diff["changed"]:
            print(
                f"    changed ({entry['division']!r}, {entry['path']!r}): "
                f"{entry['old_chars']} -> {entry['new_chars']} chars"
            )
    return 0


def _migrate(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(MIGRATION_PATH.read_text(encoding="utf-8"))
        return 0
    connection = psycopg2.connect(_database_url(args.database_url))
    try:
        apply_migration(connection)
    finally:
        connection.close()
    _print({"status": "applied", "migration": MIGRATION_PATH.name})
    return 0


def _register(args: argparse.Namespace) -> int:
    registry = CorpusRegistry(_path(args.manifest), asset_root=_path(args.pdf_root) if args.pdf_root else None)
    if args.dry_run:
        _print({
            "status": "dry_run",
            "documents": len(registry.documents),
            "source_observations": len(registry.source_observations),
            "extractions": len(registry.extraction_runs),
            "active": len(registry.active_documents),
        })
        return 0
    connection = psycopg2.connect(_database_url(args.database_url))
    try:
        with connection:
            with connection.cursor() as cursor:
                for document in registry.documents.values():
                    register_document(cursor, document)
                for observation in registry.source_observations:
                    register_source_observation(cursor, observation)
                for run in registry.extraction_runs.values():
                    register_extraction(cursor, run)
    finally:
        connection.close()
    _print({
        "status": "registered",
        "documents": len(registry.documents),
        "source_observations": len(registry.source_observations),
        "extractions": len(registry.extraction_runs),
    })
    return 0


def _ingest(args: argparse.Namespace) -> int:
    registry = CorpusRegistry(_path(args.manifest), asset_root=_path(args.pdf_root) if args.pdf_root else None)
    run = registry.extraction(args.extraction_id)
    document = registry.get(run.document_id)
    bundle = load_bundle(_path(args.bundle))
    chunks = bundle.get("chunks", [])
    if args.dry_run:
        _print({"status": "dry_run", "document_id": document.document_id, "extraction_id": run.extraction_id, "chunks": len(chunks)})
        return 0
    client = embedding_client()
    embeddings: list[list[float]] = []
    for offset in range(0, len(chunks), args.batch_size):
        response = client.embeddings.create(
            model=args.embedding_model,
            input=[item["content"] for item in chunks[offset:offset + args.batch_size]],
        )
        embeddings.extend(item.embedding for item in response.data)
    connection = psycopg2.connect(_database_url(args.database_url))
    try:
        ingest_extraction(connection, document, run, bundle, embeddings)
    finally:
        connection.close()
    _print({"status": "ingested", "document_id": document.document_id, "extraction_id": run.extraction_id, "chunks": len(chunks)})
    return 0


def _activate(args: argparse.Namespace) -> int:
    registry = CorpusRegistry(_path(args.manifest), asset_root=_path(args.pdf_root) if args.pdf_root else None)
    document = registry.get(args.document_id)
    run = registry.extraction(args.extraction_id)
    if run.document_id != document.document_id:
        raise SystemExit("document_id and extraction_id do not match")
    if args.dry_run:
        _print({"status": "dry_run", "document_id": document.document_id, "extraction_id": run.extraction_id})
        return 0
    connection = psycopg2.connect(_database_url(args.database_url))
    try:
        activate(connection, document, run)
    finally:
        connection.close()
    _print({"status": "activated", "document_id": document.document_id, "extraction_id": run.extraction_id})
    return 0


def _rollback(args: argparse.Namespace) -> int:
    if args.dry_run:
        _print({"status": "dry_run", "act_number": args.act_number, "language": args.language})
        return 0
    connection = psycopg2.connect(_database_url(args.database_url))
    try:
        document_id, extraction_id = rollback(connection, args.act_number, args.language)
    finally:
        connection.close()
    _print({"status": "rolled_back", "document_id": document_id, "extraction_id": extraction_id})
    return 0


def _rollout(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    manifest = _path(args.manifest)
    pdf_root = _path(args.pdf_root) if args.pdf_root else None
    sidecar_root = _path(args.sidecar_root)
    extraction_root = _path(args.extraction_root)
    registry = CorpusRegistry(
        manifest,
        asset_root=pdf_root,
        sidecar_root=sidecar_root,
    )
    result = rollout_corpus(
        registry,
        extraction_root=extraction_root,
        sidecar_root=sidecar_root,
        database_url=_database_url(args.database_url),
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
        max_embedding_cost_usd=args.max_embedding_cost_usd,
        document_ids=args.document_id or None,
        dry_run=args.dry_run,
        activate_ready=args.activate_ready,
    )
    if not args.verbose:
        result.pop("selected_extractions", None)
    _print(result)
    if result["failures"]:
        return 2
    return 0 if args.dry_run or result["status"] == "complete" else 2


def _upload_objects(
    registry: CorpusRegistry, scope: str
) -> tuple[list[tuple[Path, str, str, str]], list[str]]:
    """Select the objects `scope` puts online, and the errors that block them.

    Scope names match `validate` so an operator can verify exactly what was
    pushed. "registry" is not offered here: it is the byte-less scope, and an
    upload with no bytes is nothing.
    """
    documents = list(registry.documents.values())
    extraction_ids = set(registry.extraction_runs)
    if scope == "active":
        active = list(registry.active_documents.values())
        document_ids = {item.document_id for item in active}
        documents = [item for item in documents if item.document_id in document_ids]
        extraction_ids = {item.extraction_id for item in active}

    objects: list[tuple[Path, str, str, str]] = []
    errors: list[str] = []
    for document in documents:
        try:
            path = registry.validate(document)
        except Exception as exc:
            errors.append(f"{document.document_id}: {exc}")
            continue
        objects.append((path, document.asset_key, "application/pdf", document.sha256))
    for identity in sorted(extraction_ids):
        run = registry.extraction_runs[identity]
        if run.status != "ready" or run.coordinate_sidecar is None:
            continue
        try:
            path = registry.sidecar_path(run)
        except Exception as exc:
            errors.append(f"{run.extraction_id}: {exc}")
            continue
        objects.append((path, run.coordinate_sidecar.asset_key, "application/gzip", run.coordinate_sidecar.sha256))
    return objects, errors


def _upload(args: argparse.Namespace) -> int:
    registry = CorpusRegistry(
        _path(args.manifest), asset_root=_path(args.pdf_root), sidecar_root=_path(args.sidecar_root)
    )
    objects, errors = _upload_objects(registry, args.scope)
    if errors:
        _print({"status": "blocked", "scope": args.scope, "errors": errors})
        return 1
    if args.dry_run:
        _print({"status": "dry_run", "scope": args.scope, "bucket": args.bucket, "endpoint_url": args.endpoint_url, "object_count": len(objects), "total_bytes": sum(path.stat().st_size for path, *_ in objects)})
        return 0
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit("Live upload requires the optional boto3 package; dry-run does not") from exc
    # R2 rejects AWS region names outright; boto3 falls back to whatever
    # AWS_DEFAULT_REGION/~/.aws/config resolves to unless told otherwise.
    client = boto3.client("s3", endpoint_url=args.endpoint_url or None, region_name="auto")
    for path, key, content_type, digest in objects:
        client.upload_file(
            str(path), args.bucket, key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=31536000, immutable",
                "Metadata": {"sha256": digest},
            },
        )
    _print({"status": "uploaded", "scope": args.scope, "bucket": args.bucket, "object_count": len(objects)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m corpus")
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("generate-manifest", help="discover immutable PDFs and write deterministic registry/audit JSON")
    command.add_argument("--pdf-root", required=True)
    command.add_argument("--metadata-root", default="data/acts_metadata")
    command.add_argument("--index", default="data/acts_index.json")
    command.add_argument("--chunks-root", default="data/chunks/en")
    command.add_argument("--existing-manifest")
    command.add_argument("--extract-report", default="data/chunks/extract_report.json")
    command.add_argument("--output", default="data/pdfs/manifest.json")
    command.add_argument("--report", default="data/corpus/coverage.json")
    command.set_defaults(func=_generate)

    command = sub.add_parser("validate", help="validate manifest, bytes, pages, extraction identities, and sidecars")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root")
    command.add_argument("--sidecar-root")
    command.add_argument("--cdn-base-url", default=os.getenv("CORPUS_CDN_BASE_URL", ""))
    command.add_argument("--scope", choices=["registry", "active", "full"], default="full")
    command.add_argument("--deep", action="store_true")
    command.add_argument("--format", choices=["text", "json"], default="text")
    command.set_defaults(func=_validate)

    command = sub.add_parser("shadow-extract", help="re-extract exact documents and generate coordinate sidecars")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root")
    command.add_argument("--sidecar-root", default="data/corpus/sidecars")
    command.add_argument("--extraction-root", default="data/corpus/extractions")
    command.add_argument("--document-id", action="append")
    command.add_argument("--activate-ready", action="store_true")
    command.add_argument("--output")
    command.add_argument("--report", default="data/corpus/shadow-extraction-report.json")
    command.set_defaults(func=_shadow)

    command = sub.add_parser(
        "diff-extractions", help="per-document chunk-set diff between two extraction generations"
    )
    command.add_argument("--old-manifest", required=True)
    command.add_argument("--old-extraction-root", required=True)
    command.add_argument("--new-manifest", default="data/pdfs/manifest.json")
    command.add_argument("--new-extraction-root", default="data/corpus/extractions")
    command.add_argument("--document-id", action="append")
    command.add_argument("--format", choices=["text", "json"], default="text")
    command.set_defaults(func=_diff_extractions)

    command = sub.add_parser("migrate", help="apply the additive provenance schema migration")
    command.add_argument("--database-url")
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_migrate)

    command = sub.add_parser("register", help="upsert manifest documents and extraction runs")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root")
    command.add_argument("--database-url")
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_register)

    command = sub.add_parser("ingest", help="embed and atomically ingest one shadow extraction")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root")
    command.add_argument("--bundle", required=True)
    command.add_argument("--extraction-id", required=True)
    command.add_argument("--database-url")
    command.add_argument("--embedding-model", default=corpus_embedding_model())
    command.add_argument("--batch-size", type=int, default=100)
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_ingest)

    command = sub.add_parser("activate", help="atomically switch one Act/language to a ready extraction")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root")
    command.add_argument("--document-id", required=True)
    command.add_argument("--extraction-id", required=True)
    command.add_argument("--database-url")
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_activate)

    command = sub.add_parser("rollback", help="restore the previous Act/language activation")
    command.add_argument("--act-number", required=True)
    command.add_argument("--language", required=True)
    command.add_argument("--database-url")
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_rollback)

    command = sub.add_parser(
        "rollout",
        help="prepare, migrate, ingest, and activate every verified ready extraction",
    )
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root", default=os.getenv("CORPUS_LOCAL_ROOT"))
    command.add_argument(
        "--sidecar-root",
        default=os.getenv("CORPUS_SIDECAR_ROOT", "data/corpus/sidecars"),
    )
    command.add_argument("--extraction-root", default="data/corpus/extractions")
    command.add_argument("--database-url")
    command.add_argument("--embedding-model", default=corpus_embedding_model())
    command.add_argument("--batch-size", type=int, default=100)
    command.add_argument(
        "--max-embedding-cost-usd",
        type=float,
        default=1.0,
        help="hard cap for embedding requests in this run (default: $1.00)",
    )
    command.add_argument(
        "--document-id",
        action="append",
        help="limit rollout to one document identity; repeat for multiple documents",
    )
    command.add_argument("--dry-run", action="store_true")
    command.add_argument(
        "--verbose",
        action="store_true",
        help="include every selected extraction identity in the final report",
    )
    command.add_argument(
        "--no-activate",
        dest="activate_ready",
        action="store_false",
        help="prepare and ingest without changing active retrieval mappings",
    )
    command.set_defaults(func=_rollout, activate_ready=True)

    command = sub.add_parser("upload", help="upload immutable PDFs/sidecars to S3-compatible storage")
    command.add_argument("--manifest", default="data/pdfs/manifest.json")
    command.add_argument("--pdf-root", required=True)
    command.add_argument("--sidecar-root", default="data/corpus/sidecars")
    command.add_argument("--bucket", required=True)
    command.add_argument("--endpoint-url", default=os.getenv("CORPUS_S3_ENDPOINT_URL", ""))
    command.add_argument("--scope", choices=["active", "full"], default="full")
    command.add_argument("--dry-run", action="store_true")
    command.set_defaults(func=_upload)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
