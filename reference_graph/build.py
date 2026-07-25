"""Build an auditable graph candidate from one registered immutable receipt."""
from __future__ import annotations

from pathlib import Path

from corpus.registry import CorpusRegistry

from .models import (
    Candidate,
    DEFAULT_GRAPH_DOCUMENT_ID,
    Edge,
    SourceDocument,
    UnresolvedReference,
    candidate_id,
    edge_id,
    versioned_id,
)
from .pdf_text import evidence_for_literal, read_pdf
from .provisions import page_groups, parse_provisions
from .reference_lexer import lex
from .resolver import resolve


def source_document(
    repository_root: Path,
    document_id: str = DEFAULT_GRAPH_DOCUMENT_ID,
    *,
    manifest_path: Path | None = None,
    asset_root: Path | None = None,
) -> SourceDocument:
    """Resolve one exact registered document; never infer an active/latest version."""
    manifest_path = manifest_path or repository_root / "data" / "pdfs" / "manifest.json"
    asset_root = asset_root or manifest_path.parent
    registry = CorpusRegistry(manifest_path, asset_root=asset_root)
    record = registry.get(document_id)
    if record.timeline_type not in {"REPRINT", "REPRINT ONLINE"}:
        raise ValueError("snapshot_is_not_consolidated")
    pdf_path = registry.validate(record)
    try:
        relative_pdf = pdf_path.relative_to(repository_root)
        relative_manifest = manifest_path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("snapshot_path_outside_repository") from exc
    return SourceDocument(
        document_id=document_id,
        corpus_document_id=record.document_id,
        act_number=record.act_number,
        act_title=record.act_title,
        language=record.language,
        sha256=record.sha256,
        page_count=record.page_count,
        receipt_path=f"/receipts/{document_id}/pdf",
        pdf_path=str(relative_pdf),
        manifest_path=str(relative_manifest),
    )


def build_graph(repository_root: Path, document_id: str = DEFAULT_GRAPH_DOCUMENT_ID):
    """Build one graph in isolation from the exact registered PDF bytes."""
    document = source_document(repository_root, document_id)
    pdf = read_pdf(repository_root / document.pdf_path, document.sha256)
    groups = page_groups(pdf, document)
    provisions = parse_provisions(pdf, document, groups=groups)
    by_id = {item.provision_id: item for item in provisions}
    main_pages = groups.main
    schedule_pages = groups.schedules
    raw: list[tuple] = []
    for source in provisions:
        for reference in lex(source.text):
            owner = _nested_owner(provisions, source, reference.start_offset, reference.end_offset)
            if owner.provision_id != source.provision_id:
                continue
            raw.append((source, reference))
    # A node can have a repeated literal reference; retain each exact source offset but do not emit
    # the same parsed candidate twice from overlapping section/subsection text.
    seen: set[tuple[str, int, int]] = set()
    edges: list[Edge] = []
    unresolved: list[UnresolvedReference] = []
    candidates: list[Candidate] = []
    emitted_edges: set[str] = set()
    for source, reference in sorted(raw, key=lambda item: (item[0].provision_id, item[1].start_offset, item[1].literal)):
        key = (source.provision_id, reference.start_offset, reference.end_offset)
        if key in seen:
            continue
        seen.add(key)
        index_pages = schedule_pages if source.kind == "schedule" else main_pages
        evidence = evidence_for_literal(source.text, reference.start_offset, reference.end_offset, index_pages,
                                        source_start=source.start_offset, index_pages=index_pages)
        cid = candidate_id(source.provision_id, reference.start_offset, reference.literal)
        result = resolve(reference, source, by_id, document.act_number)
        if result.target_ids:
            candidates.append(Candidate(cid, source.provision_id, source.version_id, reference.literal, reference.kind,
                                        result.target_ids, "resolved", None, evidence))
            for target in result.target_ids:
                identity = edge_id(source.provision_id, target, reference.start_offset, reference.literal)
                if identity in emitted_edges:
                    continue
                emitted_edges.add(identity)
                edges.append(Edge(identity,
                                  source.provision_id, source.version_id, target,
                                  versioned_id(document.document_id, target) if target in by_id else None,
                                  "explicit_reference", reference.kind, evidence))
        else:
            reason = result.reason_code or "unresolved"
            candidates.append(Candidate(cid, source.provision_id, source.version_id, reference.literal, reference.kind,
                                        [], "unresolved", reason, evidence))
            unresolved.append(UnresolvedReference(cid, source.provision_id, source.version_id, reference.literal,
                                                  reference.kind, reason, evidence))
    return document, provisions, edges, unresolved, candidates


def _nested_owner(provisions, source, start: int, end: int):
    absolute_start, absolute_end = source.start_offset + start, source.start_offset + end
    children = [item for item in provisions if item.provision_id != source.provision_id
                and item.start_offset <= absolute_start and item.end_offset >= absolute_end
                and item.provision_id.count("/") > source.provision_id.count("/")]
    return max(children, key=lambda item: item.provision_id.count("/"), default=source)
