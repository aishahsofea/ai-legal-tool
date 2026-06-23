# Malaysian Legal Research AI Assistant

An AI agent that helps Malaysian law practitioners research legislation by answering natural-language questions with cited, statute-grounded responses. Queries can be in English, Bahasa Malaysia, or mixed. The agent never gives legal advice and escalates to a human lawyer when the query involves a specific client situation.

Built on a LangGraph agent graph backed by a pgvector corpus of section-level chunks extracted from AGC portal PDFs.

---

## Architecture

```text
User query + thread_id (EN / BM / mixed)
       │
       ▼
┌────────────────────┐
│  start_turn        │  loads this thread's history from the
│                    │  checkpointer; resets per-turn scratch state
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  router            │  classifies: statute_lookup / topical_search /
│                    │  provision_extraction / escalate
└──────┬─────────────┘
       │ (escalate short-circuits here)
       ▼
┌────────────────────┐
│  contextualize     │  rewrites an elliptical follow-up into a
│                    │  self-contained standalone query for retrieval
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  retriever         │  pgvector similarity search over section-level
│                    │  chunks (EN + BM)
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  synthesiser       │  drafts answer + citations (act, section,
│                    │  page deep-link)
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  citation_validator│  checks citation_refs against retrieved chunks
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  grounding_check   │  flags claims unsupported by retrieved chunk text
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  supervisor        │  enforces policy before output
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  record_turn       │  appends this turn to checkpointed history
└──────┬─────────────┘
       │
       ▼
      END
```

Two short-circuits aren't pictured above: a query the `router` classifies as `escalate` skips straight to `record_turn` with a fixed human hand-off message (the `escalate` node); and a `supervisor` violation with a retry remaining (`MAX_RETRIES`) loops back to `synthesiser` via `increment_retry` before re-running citation/grounding checks.

**Stack:** LangGraph (Postgres/Memory checkpointer) · FastAPI (Railway) · Next.js (Vercel) · Postgres + pgvector (Supabase) · OpenAI `text-embedding-3-small` · GPT-4.1 by default — provider-agnostic via `agent/llm_factory.py` (Claude/Gemini also supported; Claude used for the eval judge)

---

## Data Pipeline

The knowledge base is built by running five sequential steps that go from scraping the [AGC portal](https://lom.agc.gov.my) to a searchable pgvector index. Run once before starting the agent.

See [CONTRIBUTING.md](CONTRIBUTING.md) for full local setup instructions (env vars, database schema, frontend, evals).

```bash
python run.py --step all   # resumable; re-running skips completed work
```

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
├── railway.toml                    # Railway deploy config (FastAPI backend)
├── vercel.json                     # Vercel deploy config (Next.js frontend)
├── .env                            # DATABASE_URL, OPENAI_API_KEY, etc.
├── agent/
│   ├── graph.py                    # graph: nodes, edges, retry loop, checkpointer wiring
│   ├── state.py                    # AgentState, Message, Citation, QueryEvent/Result types
│   ├── query_lifecycle.py          # run_query / run_query_stream (thread_id-based)
│   ├── query_policy.py             # MAX_HISTORY_TURNS, MAX_RETRIES, history trimming
│   ├── llm_factory.py              # provider-agnostic LLM factory (Claude/Gemini/OpenAI)
│   └── nodes/
│       ├── router.py
│       ├── contextualize.py
│       ├── retriever.py
│       ├── synthesiser.py
│       ├── citation_validator.py
│       ├── grounding_check.py
│       └── supervisor.py
├── api/
│   └── main.py                     # FastAPI SSE endpoint: POST /query { query, thread_id }
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
├── evals/
│   ├── dataset.json                # hand-validated benchmark set
│   ├── assertions.py               # L1 deterministic assertions
│   ├── judge.py                    # Claude-based L2 judge
│   ├── run_evals.py                # eval runner + report writer
│   ├── debug_case.py               # single-case node-by-node tracer
│   ├── review_verdicts.py          # judge verdict review helper
│   ├── seed_test_corpus.py         # tiny eval-only pgvector seed
│   └── validate_dataset.py         # human review checklist
├── tests/                          # unit tests (graph retry, checkpointer memory, ...)
├── frontend/                       # Next.js app router chat UI (Vercel AI SDK)
├── data/
│   ├── acts_index.json
│   ├── acts_metadata/
│   ├── pdfs/en/
│   ├── chunks/en/
│   └── cache/                      # HTTP cache (SQLite, 7-day TTL)
├── .github/workflows/evals.yml     # eval smoke run (manual trigger, posts PR comment)
└── docs/
    ├── PRD.md
    ├── build-log.md
    ├── agent-hardening-backlog.md
    ├── checkpointer-implementation-plan.md
    └── adr/                        # Architecture Decision Records
```

---

## Running the API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET http://localhost:8000/health`

### Query endpoint

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does Section 17 of the Evidence Act say about admissions?", "thread_id": "demo-1"}'
```

Streams Server-Sent Events:

```text
data: {"type": "status",   "message": "Classifying query..."}
data: {"type": "status",   "message": "Searching Malaysian Acts..."}
data: {"type": "status",   "message": "Drafting response..."}
data: {"type": "status",   "message": "Checking policy compliance..."}
data: {"type": "response", "content": "...", "citations": [...], "violations": []}
data: {"type": "done"}
```

On a follow-up turn where the contextualize node rewrites the query into a standalone form, a `"Resolving follow-up..."` status is emitted before retrieval (the rewritten text itself is never surfaced). If the supervisor finds a violation and a retry remains, a `"Refining response..."` status is emitted and `synthesiser → citation_validator → grounding_check → supervisor` re-runs once (bounded by `MAX_RETRIES`). If the router classifies the query as `escalate`, an `"Escalating to human lawyer..."` status is emitted and the response is a fixed hand-off message.

Citation objects include `act_number`, `act_title`, `section_number`, `pdf_url` (with `#page=N` anchor), and `page_number`.

### Conversation memory

Every request carries a `thread_id`; the client never resends prior turns. History is kept server-side in a LangGraph checkpointer, keyed by `thread_id`:

- `DATABASE_URL` set (default) → `PostgresSaver` / `AsyncPostgresSaver`, persisted in the same Postgres instance as pgvector
- `CHECKPOINTER=memory` or no `DATABASE_URL` → in-process `MemorySaver` (local dev/tests)

History accumulates across turns and is trimmed to the most recent `MAX_HISTORY_TURNS` (3 turns = 6 messages) when read by the router, contextualize, and synthesiser nodes. Trimming slices in whole turns (user+assistant pairs), so the limit is honest about its unit and a slice never begins on a dangling assistant reply. Assistant turns are stored **disclaimer-free** — the legal-advice disclaimer is stripped at record-time so later nodes don't re-read repeated boilerplate (the disclaimer still reaches the user in the response).

---

## Eval Harness

`evals/dataset.json` contains hand-validated test cases for the Evidence Act 1950, Penal Code, PDPA 2010, Companies Act 2016, Employment Act 1955, and escalation cases that should be blocked.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run evals locally. A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered) runs a 15-case smoke eval against the GPT-4.1 defaults and posts the judge pass rate and key L1 metrics as a PR comment; it fails if the judge pass rate drops below 80%.
