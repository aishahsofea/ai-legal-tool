# Corpus-wide PDF Citation Receipts

The receipt system treats source bytes, extraction output, and activation as separate immutable lifecycle stages. A citation is enriched only when its retrieved chunk already carries an exact `document_id` and `extraction_id`; legacy Act numbers are never used to invent provenance.

## Identity and lifecycle

1. Step 3 re-observes each consolidated reprint, verifies it is an openable PDF, computes SHA-256/size/pages, and registers content-addressed bytes plus a source observation. This detects replacements even when AGC reuses a URL. Amendment-only files are blockers, not base Acts.
2. A changed hash creates `act-<act>-<language>-sha256-<fullhash>` and remains staged. Existing and historical identities remain addressable.
3. Shadow extraction validates those bytes, computes content hashes/page bounds and a chunk-set hash, and writes a deterministic gzip word-coordinate sidecar. The extraction ID binds document, extractor/version, and configuration.
4. Ingestion obtains every embedding before opening the replacement transaction. One transaction registers metadata, replaces exactly one extraction's chunks, verifies row count, and marks the extraction ready. Failures roll back the entire extraction.
5. Activation atomically switches the `(act_number, language)` mapping and records the previous mapping. Rollback restores that prior document/extraction.
6. Dual-read retrieval returns an active provenance extraction when that Act/language has one, and legacy rows only where no active mapping exists. Only exact provenance rows receive receipts; all failures retain the official AGC link.

The deterministic inventory is `data/pdfs/manifest.json`. `data/corpus/coverage.json` contains one row per audited input PDF with status, reason, remediation, effort, re-download/re-extraction flags, and official fallback.

## Storage and delivery

Development uses `CORPUS_LOCAL_ROOT` and `CORPUS_SIDECAR_ROOT`. Production uses an S3-compatible immutable bucket (Cloudflare R2 recommended) plus a custom CDN domain. Store `sha256` as object metadata and configure retention/object lock outside the app.

`RECEIPT_DELIVERY_MODE` is `auto`, `local`, `redirect`, or `proxy`. Before a CDN redirect/proxy, the API requires matching object length, `application/pdf`, and `x-amz-meta-sha256`. Sidecars pass the same metadata gate and are hash-checked again after download before decoding. GET/HEAD share SHA ETags and immutable caching; local/proxy modes support ranges. CORS must allow GET/HEAD/OPTIONS and expose range/identity headers.

The locator reads the hash-verified sidecar for v2 extractions. Live PyMuPDF word extraction exists only for saved v1 aliases during dual-read. `matched`, `not_found`, and `ambiguous` semantics are unchanged.

## Rollout

The checked-in audit has 624 inputs: 596 canonical reprints registered, 576 exact shadow extractions ready, five repaired pilots active, and 48 blocked inputs (28 amendment-only, 15 no-chunk, 5 scanned). The six BM-only documents remain `bm` sources.

The normal local/operator workflow is one idempotent command:

```bash
python3 -m corpus rollout --dry-run
python3 -m corpus rollout
```

It validates or regenerates missing bundles and sidecars, applies the migration, registers immutable identities, embeds and ingests only missing extractions, and activates every successfully verified unambiguous Act/language mapping. A rerun resumes from database and filesystem state; one failed document remains inactive without stopping the rest. Embedding submissions have a US$1 default hard cap per invocation (`--max-embedding-cost-usd` changes it), with automatic API retries disabled so the ceiling remains enforceable. Source chunks over the embedding model's token limit are segmented for embedding and their vectors are length-weighted and normalized back to one immutable chunk. `--document-id` limits the operation and `--no-activate` leaves successful ingestions in shadow mode.

Production asset upload remains intentionally operator-gated because object-storage credentials, retention, and CDN verification live outside the application:

1. apply `migrations/0001_corpus_provenance.sql` with `python -m corpus migrate`;
2. upload all registered PDFs and the 576 generated sidecars, then run full CDN metadata/byte validation;
3. register the manifest and atomically ingest shadow bundles;
4. compare row counts/chunk-set hashes and activate Act/language mappings in reviewed batches;
5. monitor availability/integrity/delivery failures and locator outcome rates;
6. use `python -m corpus rollback --act-number ... --language ...` if a batch regresses;
7. switch `CORPUS_RETRIEVAL_MODE=verified` only after legacy coverage is no longer needed.

Run `python -m corpus --help` for the generate, validate, shadow, migrate, register, ingest, activate, rollback, and upload commands. All state-changing database/storage commands have a dry-run workflow documented in `CONTRIBUTING.md`.
