# Data Pipeline

The knowledge base is built by five sequential steps that go from scraping the
[AGC portal](https://lom.agc.gov.my) to a searchable pgvector index. Run once
before starting the agent — see [CONTRIBUTING.md](../CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour)
for setup.

```bash
python run.py --step all   # idempotent; immutable identities prevent duplicate work
```

## Steps

## Separate statutory reference graph

The reference graph is intentionally **not** a sixth scraper/extraction/embedding step. It never changes chunks, active corpus mappings, retrieval, or evaluations. The API never downloads or parses PDFs.

For Act 265:

- `python3 -m reference_graph.cli catalog` reads `data/acts_metadata/265.json` and the corpus manifest offline. Strict-dated REPRINT/REPRINT ONLINE observations only, listed chronologically.
- `acquire --download --snapshot-date YYYY-MM-DD` is the only network path. Validates the response, stores immutable bytes under `data/pdfs/objects/sha256/`, registers the source observation plus content-derived document metadata — never moves the research index.
- The report sorts snapshots into ready/already-registered vs unavailable, integrity-failed, or scanned/unparseable blockers.

Timeline dates are observed snapshot labels — not exact effective dates.

`data/reference_graph/snapshot-acquisition-act-265.json` records the 2023 pilot acquisition. `snapshot-acquisition-act-265-older.json` records the rest. Current catalog state:

| Observed source date | Registered document | Readiness |
| --- | --- | --- |
| 10/01/1975 | `act-265-en-sha256-f9235f48…` | Blocked: scanned/unparseable text layer |
| 20/08/2001 | `act-265-en-sha256-96b5741a…` | Blocked: scanned/unparseable text layer |
| 24/01/2006 | `act-265-en-sha256-aaeb175a…` | Promoted/audited graph |
| 26/05/2012 | `act-265-en-sha256-1ee65655…` | Promoted/audited graph |
| 01/02/2023 | `act-265-reprint-2023-6fec2f07` | Promoted/audited Phase 1 graph |
| 02/09/2023 | `act-265-en-sha256-6ef0ba72…` | Promoted/audited comparison graph |

Each registered PDF gets parsed independently, with stable readable provision IDs and document-qualified version IDs. Cross-Act targets stay version-neutral. Candidate artifacts live under `data/reference_graph/<document_id>/.work/` — provision nodes, only literal resolved edges, unresolved reason codes, exact PDF evidence/rectangle audit material. Every attempt persists `.work/build-report.json`; an unparseable layout is `blocked`, never guessed. `verify-determinism` proves two clean builds hash identically.

A human audits every candidate against its exact receipt first. Only then can the complete approved/rejected set promote into the API-visible `provisions.json`, `edges.json`, `unresolved.json`, `audit.json`. Rejections stay visible in the unresolved/audit output. Candidate or incomplete-audit snapshots can't be loaded, selected, or compared.

Comparison unions two promoted one-hop neighborhoods and matches on a multiset key — source, target, reference kind, relationship, normalized literal wording — never on offset-derived `edge_id`. Evidence stays snapshot-specific; results are only added, removed, or unchanged (a wording change = one removed + one added). The promoted JSON artifacts are the production read source. Additive PostgreSQL graph tables mirror their counts and hashes transactionally, and never touch `chunks`.

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
- PDF selection: `latest_reprint_pdf`, or skip. An amendment never substitutes for a base Act.
- Needs an openable PDF response. Then records full SHA-256, byte size, page count, source URL/timeline, language, content-derived document/object identities.
- Every run re-observes the authoritative bytes, so same-URL replacements get caught. Unchanged hash → records a source observation, no duplicate document. Changed hash → stages a new identity, active mapping doesn't move.
- Report: `data/pdfs/download_report.json`

### Step 4 — Shadow extraction and coordinate sidecars

Validates each registered PDF, extracts section-level text with PyMuPDF, writes a bundle keyed by extraction identity under `data/corpus/extractions/` plus a deterministic gzip word-coordinate sidecar under `data/corpus/sidecars/`.

- ~700 PDFs, a few minutes (CPU-bound)
- Scanned PDFs (< 100 chars/page average) and zero-chunk results are explicit blockers
- Section boundaries detected by Malaysian Act numbering regex (`1.`, `32A.`, `90A.` etc.)
- Each chunk carries `document_id`, `extraction_id`, `content_sha256`, `page_start`, `page_end`, Act/title/section/content/language
- The extraction run records extractor/version/configuration hash, chunk-set hash/count, sidecar identity/status
- Report: `data/chunks/extract_report.json`

### Step 5 — Embed and ingest → pgvector

Embeds each shadow bundle with `text-embedding-3-small` and atomically ingests its exact extraction into Postgres (see the [corpus migration](../CONTRIBUTING.md#3-database-schema)).

- ~25,000 chunks in batches of 100 — ~5 minutes, ~$0.15 in embedding costs
- All embeddings for one extraction get obtained before database mutation — a failure commits no partial rows
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