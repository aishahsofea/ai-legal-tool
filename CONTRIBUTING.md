# Contributing

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16 with the `vector` extension ([pgvector](https://github.com/pgvector/pgvector))

### 1. Python dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Environment variables

Create `.env` in the project root:

```env
DATABASE_URL=postgresql://user@/dbname?host=/path/to/pg/socket
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=ai-legal-tool
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Database schema

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

### 4. Build the knowledge base (one-time, ~1 hour)

```bash
python run.py --step all
```

All steps are resumable — re-running skips already-completed work. Run steps individually if needed:

```bash
python run.py --step 1   # scrape Act listing pages (~1 min)
python run.py --step 2   # scrape Act detail pages (~45 min)
python run.py --step 3   # download PDFs (~18 min)
python run.py --step 4   # extract section-level chunks (~5 min)
python run.py --step 5   # embed + ingest into pgvector (~5 min, ~$0.15)
```

### 5. Start the API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET http://localhost:8000/health`

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

---

## Running Evals

Requires `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and a reachable `DATABASE_URL`.

```bash
# generate human-review checklist
python -m evals.validate_dataset --format markdown --output evals/review-checklist.md

# quick smoke test (5 cases)
python -m evals.run_evals --mode full --limit 5

# full suite
python -m evals.run_evals --mode full

# retriever + synthesiser only (no supervisor), used for before/after comparison
python -m evals.run_evals --mode baseline
```

Results are written to `evals/results.json`. CI runs the full suite on pushes to `main` and fails if citation accuracy or policy compliance drops below 80%.

### Model overrides

The router and synthesiser each have an env var that controls which Claude model they use:

| Env var | Node | Default |
|---|---|---|
| `ROUTER_MODEL` | router | `claude-sonnet-4-6` |
| `SYNTHESISER_MODEL` | synthesiser | `claude-sonnet-4-6` |

Override them to `claude-haiku-4-5-20251001` (~3× cheaper) to get fast pipeline-correctness signal without burning Sonnet budget:

```bash
# both nodes on Haiku — cheapest local smoke run
ROUTER_MODEL=claude-haiku-4-5-20251001 SYNTHESISER_MODEL=claude-haiku-4-5-20251001 \
  python3 -m evals.run_evals --smoke

# router cheap, synthesiser on Sonnet — useful when tuning synthesiser prompts
ROUTER_MODEL=claude-haiku-4-5-20251001 python3 -m evals.run_evals --smoke
```

Shell exports take priority over `.env` values, so you can temporarily override your local default in a single command. Set them in `.env` for a persistent local default.

**When to trust Haiku eval results:** L1 assertions (regex, DB lookups, string matching) are LLM-free and fully reliable regardless of model. L2 judge signal is lower-fidelity when both nodes use Haiku — useful for detecting gross failures, but do not treat a passing Haiku eval as equivalent to a passing Sonnet eval when tuning prompts. CI always uses Sonnet (no env vars set).

---

## Utility commands

```bash
python run.py --list-stubs          # list acts that failed step 2
python run.py --act 807             # manually re-scrape one act
python run.py --step 1 --dry-run    # print what would run without requests
tail -f scraper.log                 # follow pipeline logs
```
