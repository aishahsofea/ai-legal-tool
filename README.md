# AGC Legislation Scraper

Scrapes [lom.agc.gov.my](https://lom.agc.gov.my) — Malaysia's official federal legislation portal — to build a structured index of all Acts with metadata and PDF URLs.

## Prerequisites

Python 3.11+

```bash
pip3 install -r requirements.txt
```

## Phase 1: Build the Index

Phase 1 has two steps. Run them in order.

### Step 1.1 — Scrape listing pages → `data/acts_index.json`

Fetches the full list of Acts across all categories (updated, revised, repealed, amendment, translated) and writes a single index file.

```bash
python run.py --step 1
```

- ~25 HTTP requests, completes in under a minute
- Output: `data/acts_index.json`

To fetch only specific types:

```bash
python run.py --step 1 --types updated revised
```

Available types: `updated`, `revised`, `repealed`, `amendment`, `translated`

### Step 1.2 — Scrape detail pages → `data/acts_metadata/`

For each Act in the index, fetches the detail page (amendment timeline + PDF URLs) and subsidiary legislation. Writes one JSON file per Act.

```bash
python run.py --step 2
```

- ~1,756 HTTP requests at 1.5s delay — expect ~45 minutes
- Output: `data/acts_metadata/{act_number}.json`
- **Resumable:** re-running skips acts that already have an output file

By default only scrapes `updated` and `revised` acts (the ones with stable numeric IDs and full detail pages). To change:

```bash
python run.py --step 2 --detail-types updated
```

### Run both steps

```bash
python run.py --step all
```

---

## Output Format

### `data/acts_index.json`

```json
{
  "scraped_at": "2026-04-14T...",
  "totals": { "updated": 880, "repealed": 142, "amendment": 1791, "revised": 47, "translated": 23 },
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

Amendment records include additional fields: `publication_date`, `royal_assent_date`, `commencement_date_en`, `project_id`, `pdf_url_en`, `pdf_url_bm`.

### `data/acts_metadata/{act_number}.json`

```json
{
  "act_number": "56",
  "act_type": "updated",
  "scraped_at": "2026-04-14T...",
  "timeline": [
    { "date": "1950-05-06", "log_type": "ORIGINAL",      "project_id": "68",      "pdf_url": "https://lom.agc.gov.my/ilims/..." },
    { "date": "2017-11-24", "log_type": "REPRINT",        "project_id": "1734592", "pdf_url": "https://lom.agc.gov.my/ilims/..." },
    { "date": "2024-11-25", "log_type": "AMENDMENTS",     "project_id": "2459405", "pdf_url": "https://lom.agc.gov.my/ilims/..." }
  ],
  "latest_reprint_pdf": "https://lom.agc.gov.my/ilims/.../reprint Act 56 (Reprint 2017).pdf",
  "latest_amendment_pdf": "https://lom.agc.gov.my/ilims/.../Act A1732.pdf",
  "subsidiary_legislation": [
    { "pu_number": "P.U. (A) 49/2014", "title_en": "...", "status": "Principal", "pdf_url": "..." }
  ],
  "subsidiary_total": 3
}
```

`latest_reprint_pdf` is the consolidated current version (REPRINT ONLINE preferred over REPRINT). This is the PDF to download in Phase 2.

---

## Resuming After a Crash

Both steps are safe to re-run:

- **Step 1** rewrites `acts_index.json` from scratch (fast, ~40s, no harm)
- **Step 2** skips any act that already has a file in `data/acts_metadata/`. HTTP responses are also cached in `data/cache/lom_cache.sqlite` (7-day TTL), so network calls are not repeated

---

## Logs

All activity is logged to both stdout and `scraper.log`. To check progress mid-run:

```bash
tail -f scraper.log
```

---

## Project Structure

```
ai-legal-tool/
├── run.py                          # CLI entrypoint
├── requirements.txt
├── scraper/
│   ├── config.py                   # URLs, delays, output paths
│   ├── session.py                  # requests-cache + retry setup
│   ├── step1_index.py              # Step 1.1 implementation
│   ├── step2_detail.py             # Step 1.2 implementation
│   └── parsers/
│       ├── index_parser.py         # normalize per-type listing records
│       ├── detail_parser.py        # parse act-detail HTML timeline
│       └── subsid_parser.py        # normalize subsidiary legislation records
└── data/
    ├── acts_index.json             # Step 1.1 output
    ├── acts_metadata/              # Step 1.2 output (one file per act)
    └── cache/                      # HTTP cache (SQLite)
```

---

## Phase 2: Download PDFs

Downloads the canonical PDF for each Act. Run after both Step 1 and Step 2 are complete.

```bash
python run.py --step 3
```

- ~700 HTTP downloads at 1.5s delay — expect ~18 minutes
- Output: `data/pdfs/en/{act_number}.pdf`
- **Resumable:** re-running skips acts that already have a PDF file

### PDF selection logic

For each act, the downloader tries in order:

1. `latest_reprint_pdf` — preferred; consolidated current text of the Act
2. `latest_amendment_pdf` — fallback for acts with no reprint (~25 acts)
3. Skip — acts with neither URL are logged as `no_pdf` (~250 acts, typically very old ordinances)

### Output

Downloads go to `data/pdfs/en/` (English only for v1; BM PDFs added in a later phase).

A summary report is written to `data/pdfs/download_report.json`:

```json
{
  "downloaded": 698,
  "skipped_exists": 0,
  "skipped_no_url": 248,
  "failed": 4,
  "failures": [
    { "act_number": "X", "url": "...", "reason": "timeout" }
  ]
}
```

### Implementation notes

- **URL encoding:** ~99% of PDF URLs contain literal spaces (e.g. `Act 56 (Reprint 2017).pdf`). The downloader encodes URLs with `urllib.parse.quote(url, safe=':/')` before fetching.
- **Timeout:** 120s per file — reprint PDFs can be large (200+ pages).
- **Session:** reuses the same `requests-cache` session as Steps 1–2 for consistent headers and retry behaviour.

### Validate before running

Test that the server accepts programmatic downloads:

```bash
curl -L "https://lom.agc.gov.my/ilims/upload/portal/akta/LOM/EN/Draf%20Bersih-Act%20729%20-PPPUU.pdf" -o test.pdf
```

If `test.pdf` is a valid PDF, the script will work. If it returns HTML, the session warmup in `session.py` is needed (already handled).

---

## Phase 3: Extract and Chunk Text

Extracts section-level structured text from each PDF using pymupdf.

- Input: `data/pdfs/en/{act_number}.pdf`
- Output: `data/chunks/en/{act_number}.json` — one entry per section
- **Scanned PDF detection:** if a PDF yields fewer than ~100 characters per page on average, it is flagged as `is_scanned` and skipped. Coverage gap is documented.
- Each chunk includes: `act_number`, `act_title`, `section_number`, `content`, `page_number`, `language`

The `page_number` field enables section-level deep links in the UI: `{pdf_url}#page={page_number}`.
