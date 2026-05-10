# Malaysian Legal Research AI Assistant

An AI agent that helps Malaysian law practitioners research legislation by answering natural-language questions with cited, statute-grounded responses. Queries can be in English, Bahasa Malaysia, or mixed. The agent never gives legal advice and escalates to a human lawyer when the query involves a specific client situation.

Built on a LangGraph agent graph backed by a pgvector corpus of section-level chunks extracted from AGC portal PDFs.

---

## Architecture

```text
User query (EN / BM / mixed)
        │
        ▼
  ┌─────────────┐
  │   router    │  classifies: statute_lookup / topical_search /
  │             │  provision_extraction / escalate
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │  retriever  │  pgvector similarity search over section-level chunks
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ synthesiser │  drafts answer + citations (act, section, page deep-link)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ supervisor  │  enforces policy before output; blocks or rewrites;
  │             │  routes to human hand-off if unresolvable
  └─────────────┘
```

**Stack:** LangGraph · FastAPI (Railway) · Next.js (Vercel) · Postgres + pgvector (Supabase) · OpenAI `text-embedding-3-small` · Anthropic Claude

---

## Data Pipeline

The knowledge base is built by running five sequential steps that go from scraping the [AGC portal](https://lom.agc.gov.my) to a searchable pgvector index. Run once before starting the agent.

### Prerequisites

```bash
pip3 install -r requirements.txt
```

Create a `.env` file:

```env
DATABASE_URL=postgresql://user@/dbname?host=/path/to/pg/socket
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=...          # for the agent (step 6+)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...          # LangSmith tracing
LANGCHAIN_PROJECT=ai-legal-tool
```

### Run the full pipeline

```bash
python run.py --step all
```

Or run each step individually:

```bash
python run.py --step 1   # scrape Act listing pages
python run.py --step 2   # scrape Act detail pages (metadata + PDF URLs)
python run.py --step 3   # download PDFs
python run.py --step 4   # extract section-level chunks
python run.py --step 5   # embed chunks and ingest into pgvector
```

All steps are resumable — re-running skips already-completed work.

---

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

Embeds each chunk with `text-embedding-3-small` and inserts into Postgres.

Requires the `chunks` table:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE chunks (
    id             BIGSERIAL PRIMARY KEY,
    act_number     TEXT NOT NULL,
    act_title      TEXT,
    section_number TEXT,
    content        TEXT,
    page_number    INT,
    language       TEXT DEFAULT 'en',
    embedding      vector(1536)
);
```

- ~25,000 chunks in batches of 100 — ~5 minutes, ~$0.15 in embedding costs
- Resumable: skips acts already present in the DB
- Builds an HNSW index after ingestion for fast similarity search

---

## Output Formats

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

---

## Project Structure

```text
ai-legal-tool/
├── run.py                          # CLI entrypoint (steps 1–5)
├── requirements.txt
├── .env                            # DATABASE_URL, OPENAI_API_KEY, etc.
├── scraper/
│   ├── config.py                   # paths, delays, URLs
│   ├── session.py                  # requests-cache + retry setup
│   ├── step1_index.py              # Step 1: scrape Act listing
│   ├── step2_detail.py             # Step 2: scrape Act detail pages
│   ├── step3_pdfs.py               # Step 3: download PDFs
│   ├── step4_extract.py            # Step 4: extract section chunks
│   └── parsers/
│       ├── index_parser.py
│       ├── detail_parser.py
│       └── subsid_parser.py
├── ingestion/
│   └── step5_ingest.py             # Step 5: embed + ingest into pgvector
├── data/
│   ├── acts_index.json
│   ├── acts_metadata/
│   ├── pdfs/en/
│   ├── chunks/en/
│   └── cache/                      # HTTP cache (SQLite, 7-day TTL)
└── docs/
    ├── PRD.md
    ├── build-log.md
    └── adr/                        # Architecture Decision Records
```

---

## Running the API

Start the FastAPI backend (requires steps 1–5 complete and `.env` configured):

```bash
uvicorn api.main:app --port 8000 --reload
```

- API runs at `http://localhost:8000`
- Auto-reloads on file changes (`--reload` flag)
- Health check: `GET http://localhost:8000/health`

### Query endpoint

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does Section 17 of the Evidence Act say about admissions?"}'
```

Streams Server-Sent Events:

```
data: {"type": "status",   "message": "Classifying query..."}
data: {"type": "status",   "message": "Found 8 relevant sections. Drafting response..."}
data: {"type": "status",   "message": "Drafting response..."}
data: {"type": "status",   "message": "Checking policy compliance..."}
data: {"type": "response", "content": "...", "citations": [...], "violations": []}
data: {"type": "done"}
```

Citation objects include `act_number`, `act_title`, `section_number`, `pdf_url` (with `#page=N` anchor), and `page_number`.

---

## Logs

All pipeline activity is logged to stdout and `scraper.log`:

```bash
tail -f scraper.log
```

## Utility commands

```bash
python run.py --list-stubs          # list acts that failed step 2
python run.py --act 807             # manually re-scrape one act (5 min timeout)
python run.py --step 1 --dry-run    # print what would run without making requests
```
