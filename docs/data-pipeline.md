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

Since 2026-09 (issue #64), AGC encrypts every listing response with AES-256-GCM. Step 1 scrapes the decryption key from `principal.php` at the start of each run, then decrypts each page before parsing. The key is never hardcoded, since AGC can rotate it without notice. A page that fails to decrypt raises and aborts the run; it is never treated as zero records.

For the `updated` and `revised` types, each listing row also carries a signed `processFile.php` link per language (AGC's replacement for the old `act-detail.php?act=&lang=` query, which AGC now rejects). Step 1 stores these as `title_link_en` / `title_link_bm` on the Act record — empty when that language has no detail page at all. Step 2 fetches these links directly instead of building its own URL.

- ~25 HTTP requests, under a minute
- To fetch specific types: `python run.py --step 1 --types updated revised`

### Step 2 — Scrape Act detail pages → `data/acts_metadata/`

For each Act, Step 2 fetches the signed detail link Step 1 captured for English and for Malay, independently — neither fetch gates the other. It also fetches subsidiary legislation, which is separately AES-256-GCM encrypted; Step 2 scrapes its own copy of the decryption key at the start of the run. One JSON file per Act.

The primary fields (`detail_url`, `timeline`, `latest_reprint_pdf`, `latest_amendment_pdf`) hold English, or Malay when an Act has no English version at all — so an already-registered document's language never moves. A genuine second version lands in the parallel `_bm`-suffixed fields.

- ~1,756 HTTP requests at 1.5s delay for the primary language — ~45 minutes. Each Act with a separate BM version adds one more request, up to ~90 minutes total on a full rescrape
- Resumable: skips acts whose file already has both languages recorded. An Act scraped before the BM fetch existed gets its BM fields backfilled on the next run, using the current listing's stored Malay link. Its existing primary fields are left untouched
- The listing is authoritative for which languages exist: an empty `title_link_bm` means confirmed absent, recorded immediately. A stored link can fail to fetch for several reasons (stale token, timeout, connection error). Any such failure is treated as transient: left for a later run, never recorded as confirmed absent
- By default scrapes `updated` and `revised` acts only — the only types with stable numeric IDs, full detail pages, and signed links from Step 1

### Step 3 — Download and register immutable reprints

Downloads the canonical reprint(s) for each Act into content-addressed local storage and updates `data/pdfs/manifest.json` atomically. An Act with both a BI and a BM reprint registers two separate documents.

- Downloads run concurrently — 636 fetches in 19s on the English-only corpus. An Act with a BM reprint adds a second fetch, so a bilingual run is roughly double that. `DOWNLOAD_CONCURRENCY`, backoff, and failure reasons are in [CONTRIBUTING](../CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour)
- Registration is not parallel. The manifest write stays on one thread, so identity never depends on the order downloads finish
- Every failure in the report carries a reason
- PDF selection: `latest_reprint_pdf` (primary) and `latest_reprint_pdf_bm` (secondary), or skip. An amendment never substitutes for a base Act, in either language.
- Needs an openable PDF response. Then records full SHA-256, byte size, page count, source URL/timeline, language, content-derived document/object identities.
- Every run re-observes the authoritative bytes, so same-URL replacements get caught. Unchanged hash → records a source observation, no duplicate document. Changed hash → stages a new identity, active mapping doesn't move.
- New BM documents land as unactivated shadow rows — activating them for retrieval is separate, manual work.
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

Embeds each shadow bundle with the corpus embedding model, then atomically ingests its exact extraction into Postgres. See the [corpus migration](../CONTRIBUTING.md#3-database-schema) for the schema and [model overrides](../CONTRIBUTING.md#model-overrides) for the embedding model.

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
  "timeline_bm": [
    { "date": "2017-11-24", "log_type": "REPRINT", "pdf_url": "https://lom.agc.gov.my/..." }
  ],
  "latest_reprint_pdf_bm": "https://lom.agc.gov.my/...",
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