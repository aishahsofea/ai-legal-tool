"""Build an auditable graph candidate from the immutable Act 265 receipt only."""
from __future__ import annotations

import json
from pathlib import Path

from .models import Candidate, Edge, GRAPH_DOCUMENT_ID, SourceDocument, UnresolvedReference, candidate_id, edge_id, versioned_id
from .pdf_text import evidence_for_literal, read_pdf
from .provisions import parse_provisions
from .reference_lexer import lex
from .resolver import resolve

EXPECTED_SHA256 = "6fec2f07b49d8f381851906781259b1e09a2152db8dcf1599ab77a592eae100b"


def source_document(repository_root: Path, document_id: str = GRAPH_DOCUMENT_ID) -> SourceDocument:
    manifest_path = repository_root / "data" / "pdfs" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus_id = manifest.get("aliases", {}).get(document_id)
    if not corpus_id:
        raise ValueError("snapshot_alias_not_found")
    record = next((item for item in manifest.get("documents", []) if item.get("document_id") == corpus_id), None)
    if not record or record.get("sha256") != EXPECTED_SHA256 or int(record.get("page_count", 0)) != 127:
        raise ValueError("snapshot_metadata_mismatch")
    pdf_path = repository_root / "data" / "pdfs" / "en" / "265.pdf"
    return SourceDocument(document_id, str(corpus_id), "265", str(record["act_title"]), "en", EXPECTED_SHA256, 127,
                          f"/receipts/{document_id}/pdf", str(pdf_path.relative_to(repository_root)),
                          str(manifest_path.relative_to(repository_root)))


def _nested_owner(provisions, source, start: int, end: int):
    absolute_start, absolute_end = source.start_offset + start, source.start_offset + end
    children = [item for item in provisions if item.provision_id != source.provision_id
                and item.start_offset <= absolute_start and item.end_offset >= absolute_end
                and item.provision_id.count("/") > source.provision_id.count("/")]
    return max(children, key=lambda item: item.provision_id.count("/"), default=source)


def build_graph(repository_root: Path, document_id: str = GRAPH_DOCUMENT_ID):
    document = source_document(repository_root, document_id)
    pdf = read_pdf(repository_root / document.pdf_path, document.sha256)
    provisions = parse_provisions(pdf, document)
    by_id = {item.provision_id: item for item in provisions}
    main_pages = [page for page in pdf.pages if 12 <= page.page_number <= 111]
    schedule_pages = [page for page in pdf.pages if 112 <= page.page_number <= 115]
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
