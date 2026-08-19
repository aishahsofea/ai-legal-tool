# Corpus-wide PDF Citation Receipts

The receipt system treats source bytes, extraction output, and activation as separate immutable lifecycle stages. A citation gets enriched only when its retrieved chunk already carries an exact `document_id` and `extraction_id`. Legacy Act numbers never invent provenance.

## Identity and lifecycle

PDF registration and shadow extraction (Steps 3–4) are covered in [docs/data-pipeline.md](data-pipeline.md). A changed hash there stages a new identity as `act-<act>-<language>-sha256-<fullhash>`; existing and historical identities stay addressable. What the receipt system adds on top:

1. Ingestion obtains every embedding before opening the replacement transaction. One transaction: registers metadata, replaces exactly one extraction's chunks, verifies row count, marks the extraction ready. Failures roll back the entire extraction.
2. Activation atomically switches the `(act_number, language)` mapping, records the previous mapping. Rollback restores that prior document/extraction.
3. Dual-read retrieval returns an active provenance extraction when one exists for that Act/language, legacy rows otherwise. Only exact provenance rows get receipts — every failure falls back to the official AGC link.

Deterministic inventory: `data/pdfs/manifest.json`. `data/corpus/coverage.json` holds one row per audited input PDF — status, reason, remediation, effort, re-download/re-extraction flags, official fallback.

## Storage and delivery

Development: `CORPUS_LOCAL_ROOT` and `CORPUS_SIDECAR_ROOT`. Production: an S3-compatible immutable bucket (Cloudflare R2 recommended) plus a custom CDN domain. Store `sha256` as object metadata; configure retention/object lock outside the app.

`RECEIPT_DELIVERY_MODE` is one of `auto`, `local`, `redirect`, `proxy`. Before a CDN redirect/proxy, the API requires matching object length, `application/pdf`, and `x-amz-meta-sha256`. Sidecars pass the same gate, hash-checked again after download, before decoding. GET/HEAD share SHA ETags and immutable caching; local/proxy modes support ranges. CORS must allow GET/HEAD/OPTIONS and expose range/identity headers.

The locator reads the hash-verified sidecar for v2 extractions. Live PyMuPDF word extraction only exists for saved v1 aliases, during dual-read. `matched`, `not_found`, `ambiguous` semantics unchanged.

## Rollout

The checked-in audit: 624 inputs, 596 canonical reprints registered, 576 exact shadow extractions ready, five repaired pilots active, 48 blocked (28 amendment-only, 15 no-chunk, 5 scanned). The six BM-only documents stay `bm` sources.

One idempotent command for the normal local/operator workflow:

```bash
python3 -m corpus rollout --dry-run
python3 -m corpus rollout
```

Full flag semantics (embedding cost cap, `--document-id`, `--no-activate`, resumability) are in [CONTRIBUTING.md](../CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour).

Production asset upload stays intentionally operator-gated — object-storage credentials, retention, and CDN verification live outside the application:

1. Apply `migrations/0001_corpus_provenance.sql` with `python -m corpus migrate`.
2. Upload all registered PDFs and the 576 generated sidecars, then run full CDN metadata/byte validation.
3. Register the manifest and atomically ingest shadow bundles.
4. Compare row counts/chunk-set hashes and activate Act/language mappings in reviewed batches.
5. Monitor availability/integrity/delivery failures and locator outcome rates.
6. Use `python -m corpus rollback --act-number ... --language ...` if a batch regresses.
7. Switch `CORPUS_RETRIEVAL_MODE=verified` only once legacy coverage is no longer needed.

Run `python -m corpus --help` for the generate, validate, shadow, migrate, register, ingest, activate, rollback, and upload commands. Every state-changing database/storage command has a dry-run, documented in `CONTRIBUTING.md`.