# Data Pipeline

The knowledge base is built by five sequential steps that go from scraping the
[AGC portal](https://lom.agc.gov.my) to a searchable pgvector index. Run once
before starting the agent — see [CONTRIBUTING.md](../CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour)
for setup.

```bash
python run.py --step all   # resumable; re-running skips completed work
```

## Steps

### Step 1 — Scrape Act index → `data/acts_index.json`

Fetches the full list of Acts across all categories (updated, revised, repealed, amendment, translated).

- ~25 HTTP requests, under a minute
- To fetch specific types: `python run.py --step 1 --types updated revised`

### Step 2 — Scrape Act detail pages → `data/acts_metadata/`

For each Act, fetches the detail page (amendment timeline + PDF URLs) and subsidiary legislation. One JSON file per Act.

- ~1,756 HTTP requests at 1.5s delay — ~45 minutes
- Resumable: skips acts that already have an output file
- By default scrapes `updated` and `revised` acts only (the ones with stable numeric IDs and full detail pages)

### Step 3 — Download PDFs → `data/pdfs/en/`

Downloads the canonical PDF for each Act.

- ~700 downloads at 1.5s delay — ~18 minutes
- PDF selection: `latest_reprint_pdf` → `latest_amendment_pdf` → skip (~250 old ordinances have no PDF)
- Report written to `data/pdfs/download_report.json`

### Step 4 — Extract section chunks → `data/chunks/en/`

Extracts section-level text from each PDF using pymupdf.

- ~700 PDFs, a few minutes (CPU-bound)
- Scanned PDFs (< 100 chars/page average) are detected and skipped (~50 acts)
- Section boundaries detected by Malaysian Act numbering regex (`1.`, `32A.`, `90A.` etc.)
- Each chunk: `act_number`, `act_title`, `section_number`, `content`, `page_number`, `language`
- `page_number` enables `{pdf_url}#page={n}` deep links in the frontend
- Report written to `data/chunks/extract_report.json`

### Step 5 — Embed and ingest → pgvector

Embeds each chunk with `text-embedding-3-small` and inserts into Postgres (see the
[`chunks` table schema](../CONTRIBUTING.md#3-database-schema)).

- ~25,000 chunks in batches of 100 — ~5 minutes, ~$0.15 in embedding costs
- Resumable: skips acts already present in the DB
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

### `data/chunks/en/{act_number}.json`

```json
[
  {
    "act_number": "56",
    "act_title": "EVIDENCE ACT 1950",
    "section_number": "32A",
    "content": "32A.  Admissibility of statements...",
    "page_number": 47,
    "language": "en"
  }
]
```
