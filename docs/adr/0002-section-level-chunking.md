# Chunk Acts at section level, not page or token level

Malaysian Acts are structured as Part → Division → Section → Subsection → Paragraph. Practitioners cite by section number ("Section 114 of the Evidence Act"), not by page. Page-level chunking splits sections across chunks, which breaks citation accuracy. Fixed-token chunking is worse — it discards section boundaries entirely.

Section-level chunking is the only approach that gives citation-accurate retrieval and supports deterministic `lookup_section()` tool calls. Act/Part/Section number get stored as metadata on each chunk.

## Consequences

Phase 3 (PDF text extraction) must identify and respect section boundaries, not just extract raw text. This requires:
- Regex-based section header detection on text-layer PDFs (pymupdf)
- Scanned PDFs are skipped for v1: detected by low character count per page (< ~100 chars), flagged as `is_scanned`, excluded from ingestion. Coverage gap acknowledged.
