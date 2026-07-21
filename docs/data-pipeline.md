# Data Pipeline

The knowledge base is built by five sequential steps that go from scraping the
[AGC portal](https://lom.agc.gov.my) to a searchable pgvector index. Run once
before starting the agent — see [CONTRIBUTING.md](../CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour)
for setup.

```bash
python run.py --step all   # idempotent; immutable identities prevent duplicate work
```

## Steps

## Separate statutory reference graph (Phase 1)

The reference graph is intentionally **not** a sixth scraper/extraction/embedding step. For Act 265 it reads only the existing immutable PDF snapshot and manifest alias offline, then writes a deterministic candidate under `data/reference_graph/act-265-reprint-2023-6fec2f07/.work/`. It does not download bytes, alter Act metadata, regenerate chunks, touch pgvector retrieval, or run embeddings.

Candidate artifacts contain provision nodes, explicit resolved edges, unresolved candidates with reason codes, and a PDF-receipt audit list. A human must audit every edge before a complete decision set can be promoted into the API-visible `provisions.json`, `edges.json`, `unresolved.json`, and `audit.json` index. The graph database migration is additive and has no `chunks` mutation.

### Step 1 — Scrape Act index → `data/acts_index.json`

Fetches the full list of Acts across all categories (updated, revised, repealed, amendment, translated).

- ~25 HTTP requests, under a minute
- To fetch specific types: `python run.py --step 1 --types updated revised`

### Step 2 — Scrape Act detail pages → `data/acts_metadata/`

For each Act, fetches the detail page (amendment timeline + PDF URLs) and subsidiary legislation. One JSON file per Act.

- ~1,756 HTTP requests at 1.5s delay — ~45 minutes
- Resumable: skips acts that already have an output file
- By default scrapes `updated` and `revised` acts only (the ones with stable numeric IDs and full detail pages)

### Step 3 — Download and register immutable reprints

Downloads the canonical reprint for each Act into content-addressed local storage and updates `data/pdfs/manifest.json` atomically.

- ~700 downloads at 1.5s delay — ~18 minutes
- PDF selection: `latest_reprint_pdf` → skip. An amendment is never accepted as a base-Act substitute.
- Requires an openable PDF response, then records full SHA-256, byte size, page count, source URL/timeline, language, and content-derived document/object identities.
- Every run re-observes the authoritative reprint bytes so same-URL replacements are detected. An unchanged hash records a source observation without duplicating the document; a changed hash stages a new identity without moving the active mapping.
- Report written to `data/pdfs/download_report.json`

### Step 4 — Shadow extraction and coordinate sidecars

Validates each registered PDF, extracts section-level text with PyMuPDF, and writes a bundle keyed by extraction identity under `data/corpus/extractions/` plus a deterministic gzip word-coordinate sidecar under `data/corpus/sidecars/`.

- ~700 PDFs, a few minutes (CPU-bound)
- Scanned PDFs (< 100 chars/page average) and zero-chunk results are explicit blockers
- Section boundaries detected by Malaysian Act numbering regex (`1.`, `32A.`, `90A.` etc.)
- Each chunk carries `document_id`, `extraction_id`, `content_sha256`, `page_start`, `page_end`, Act/title/section/content/language
- The extraction run records extractor/version/configuration hash, chunk-set hash/count, and sidecar identity/status
- Report written to `data/chunks/extract_report.json`

### Step 5 — Embed and ingest → pgvector

Embeds each shadow bundle with `text-embedding-3-small` and atomically ingests its exact extraction into Postgres (see the [corpus migration](../CONTRIBUTING.md#3-database-schema)).

- ~25,000 chunks in batches of 100 — ~5 minutes, ~$0.15 in embedding costs
- All embeddings for one extraction are obtained before database mutation; a failure commits no partial rows
- Resumable/idempotent by `extraction_id`, not Act number
- Activation is a separate verified pointer switch per Act/language, with rollback history
- Builds an HNSW index after ingestion for fast similarity search

## Output formats

### `data/acts_index.json`

```json
{
  "scraped_at": "2026-04-14T...",
  "totals": {
    "updated": 880,
    "revised": 47,
    "repealed": 142,
    "amendment": 1791,
    "translated": 23
  },
  "acts": [
    {
      "act_number": "56",
      "act_type": "updated",
      "title_bm": "AKTA KETERANGAN 1950",
      "title_en": "EVIDENCE ACT 1950"
    }
  ]
}
```

### `data/acts_metadata/{act_number}.json`

```json
{
  "act_number": "56",
  "timeline": [
    { "date": "1950-05-06", "log_type": "ORIGINAL", "pdf_url": "https://lom.agc.gov.my/..." },
    { "date": "2017-11-24", "log_type": "REPRINT",  "pdf_url": "https://lom.agc.gov.my/..." }
  ],
  "latest_reprint_pdf": "https://lom.agc.gov.my/...",
  "subsidiary_legislation": [...]
}
```

### `data/corpus/extractions/{extraction_id}.chunks.json`

```json
{
  "schema_version": 2,
  "document": { "document_id": "act-56-en-sha256-...", "sha256": "..." },
  "extraction": { "extraction_id": "extraction-sha256-...", "chunk_set_hash": "..." },
  "chunks": [{
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "32A",
    "content": "32A.  Admissibility of statements...",
    "page_number": 47,
    "page_start": 47,
    "page_end": 48,
    "content_sha256": "...",
    "document_id": "act-56-en-sha256-...",
    "extraction_id": "extraction-sha256-...",
    "language": "en"
  }]
}
```
