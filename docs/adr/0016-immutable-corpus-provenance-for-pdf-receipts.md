# Immutable corpus provenance for PDF Citation Receipts

Date: 2026-07-20

The Citation Receipt pilot attached five PDFs through a hand-authored manifest keyed by Act number. That was sufficient to validate the viewer, but not to prove corpus-wide that the displayed PDF was the exact document used for extraction and page numbering. The scraper also wrote mutable `data/pdfs/en/{act}.pdf` paths, retrieval rows carried no document identity, and ingestion could leave partial Act data. A remote AGC URL or matching Act number is not immutable provenance: either can point at different bytes later.

This ADR establishes a corpus lifecycle in which source bytes, extraction output, database activation, and receipt delivery are separately identified and verified. The previous five-Act manifest remains supported only as a dual-read compatibility layer while the corpus is migrated.

## Decisions

- **Receipt Documents use content-derived identities.** A registered PDF is identified as `act-<act>-<language>-sha256-<fullhash>` and stored under a SHA-256 asset key. Its hash, byte size, page count, original source URL, timeline metadata, scrape timestamp, source language, and lifecycle status are recorded. A changed hash creates a new document; it never overwrites or reassigns the old identity.
- **Source language comes from authoritative source metadata, not a legacy folder name.** BM-only Acts 144, 152, 194, 220, 228, and 230 remain BM sources even though their historical files lived under `data/pdfs/en`. Amendment-only PDFs are never accepted as consolidated base Acts.
- **Extraction Runs are immutable identities bound to one Receipt Document.** The identity includes the document, extractor, extractor version, and configuration hash. Each run records a chunk-set hash, content hashes, physical page bounds, and a deterministic word-coordinate sidecar. Replaying the same identity with different chunks or coordinates is integrity drift and is rejected rather than updated.
- **Retrieval provenance is explicit.** New chunks carry `document_id` and `extraction_id`; synthesis and grounding attach evidence only when those exact identities match. Legacy chunks are not assigned provenance by Act-number inference.
- **Activation is a reversible pointer per `(Act, language)`.** Registration and shadow ingestion do not make new bytes retrievable. An operator activates only a ready exact extraction, and activation history retains the previous document/extraction for rollback. During dual-read, an activated provenance extraction owns its Act/language; legacy rows remain fallback only where no active mapping exists.
- **Receipt delivery and location fail closed.** Local or CDN metadata must match the registry before a receipt is enriched or served. PDF GET/HEAD, ranges, ETags, and cache semantics refer to immutable bytes. Coordinate sidecars are verified before decoding. Missing, corrupt, mismatched, ambiguous, or unavailable provenance yields no receipt/highlight and retains the separate official AGC link.
- **Production assets live in immutable object storage.** Cloudflare R2 behind a custom CDN is the production default, with an S3-compatible adapter and local filesystem implementation for development/tests. Historical assets are retained indefinitely. Corpus-wide public redistribution is accepted for these source documents.
- **Corpus lifecycle operations use an operator CLI, `python -m corpus`.** Manifest generation, deep validation, shadow extraction, migration, registration, ingestion, upload, activation, and rollback are offline/batch control-plane operations. They can be large, credentialed, and deliberately reviewed; exposing them as runtime HTTP endpoints would unnecessarily expand the production attack surface. State-changing commands support dry-run or explicit per-identity inputs.
- **Coverage is generated, not curated.** `data/pdfs/manifest.json` and `data/corpus/coverage.json` are deterministic artifacts built from scraper metadata and actual bytes. Every input PDF receives an enabled/ready/blocked result with a reason, remediation, effort, re-download/re-extraction requirement, and official fallback.

## Considered options

- **Extend the static Act-number allowlist.** Rejected. It cannot represent multiple languages or historical versions, requires manual updates, and cannot prove that retrieval used the displayed bytes.
- **Infer document identity for existing chunks from Act number or current local filename.** Rejected. Mutable paths and Act numbers do not prove which historical bytes produced page numbers or text. Legacy chunks must be shadow re-extracted and re-embedded.
- **Treat the latest AGC URL as the receipt.** Rejected. Remote bytes and pagination can change independently of an existing answer. The AGC URL remains an official-current-source escape hatch, not evidence of immutable provenance.
- **Use amendment PDFs when no reprint exists.** Rejected. An amendment instrument is not the consolidated base Act and can misstate the source behind retrieved base-Act text.
- **Activate immediately after scraping or extraction.** Rejected. A new hash must finish extraction, coordinate generation, embedding, database verification, and review before it can replace an active mapping.
- **Expose migration/upload/activation as API endpoints.** Rejected. These are infrequent operator actions with broad database/object-store authority. A CLI is easier to audit, dry-run, automate in CI, and keep outside the public runtime surface.
- **Check all generated pilot hashes into `.gitignore` exceptions.** Rejected. Already tracked pilot fixtures remain tracked even under the general generated-output ignore rule; enumerating content hashes creates needless maintenance whenever a pilot is re-extracted.

## Consequences

- New or same-URL-replaced PDFs are re-observed and automatically registered by content identity, but cannot affect retrieval until their exact extraction is embedded and activated.
- Existing citations continue through the legacy side of dual-read; provenance-backed citations progressively replace them in reviewed batches.
- The schema gains immutable document/source/extraction tables, nullable provenance columns for legacy chunks, active mappings, and activation history. Ingestion becomes per-extraction and transactional instead of skipping or partially persisting an Act.
- Runtime receipt availability depends on verified PDF and sidecar assets. R2 retention, custom-domain CORS, upload, CDN deep validation, database migration, shadow embedding, and activation remain explicit deployment steps rather than application startup behavior.
- Full generated extraction bundles and sidecars are intentionally not committed. The five tracked pilot fixtures support local compatibility and smoke tests; the corpus-wide set is regenerated and uploaded immutably.
- The initial audit is frozen at 624 input PDFs: 596 canonical reprints registered, 576 extraction identities ready, five pilots active, and 48 blocked inputs (28 amendment-only, 15 no-chunk, 5 scanned/image-only). The six BM-only sources remain labeled `bm`.

## Related

- ADR 0002 — section-level chunking and the original scanned-PDF exclusion.
- ADR 0004 — bilingual retrieval and embedding strategy.
- ADR 0006 — deployment infrastructure; this decision adds the immutable corpus asset plane.
- ADR 0011 — structured citation validation; exact document/extraction identities extend the same structured-data principle to receipt provenance.
