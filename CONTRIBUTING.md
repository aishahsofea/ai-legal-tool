# Contributing

## Workflow

Do **not** commit directly to `main`. For every change — including small fixes and anything an AI agent makes on your behalf — create a new branch, push it, and open a pull request:

```bash
git switch -c <type>/<short-description>   # e.g. fix/citation-links-new-tab
# ...make changes, commit...
git push -u origin <branch>
gh pr create
```

Use a `<type>/` prefix that matches the change: `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`. `main` stays deployable and every change lands through a reviewable PR.

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

Optional flags (both default off / to Postgres):

- `CHECKPOINTER=memory` — force the in-process `MemorySaver` + `InMemoryStore` instead of Postgres (handy for local runs without a database; the test suite sets this automatically).
- `SEMANTIC_MEMORY_RECALL=on` — enable the `recall` node so the synthesiser **reads** cross-thread **Semantic Memory** (ADR 0010). Off by default, fail-open.
- `SEMANTIC_MEMORY_EXTRACT=on` — enable the background **write** path (`agent/memory/extractor.py`) that extracts durable practitioner facts (including the practitioner's own background — ADR 0012) after a legal or conversational turn and upserts them into the store. Off by default, fail-open, and runs off the hot path (after the response is delivered). Turn both flags on to see recall surface facts written on earlier turns.
- `SEMANTIC_MEMORY_PRUNE=on` — enable the background **maintenance** path (`agent/memory/pruner.py`) that consolidates duplicate profiles / near-duplicate topics and evicts low-value topics by importance+recency (not TTL). Off by default, fail-open, off the hot path, size-debounced, and conservative (never deletes the sole profile or empties a namespace).

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

Results are written to `evals/results.json` by default. A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered via `workflow_dispatch`) runs a 15-case smoke eval against the production model defaults and posts the judge pass rate and key L1 metrics as a PR comment; it fails if the judge pass rate drops below 80%.

### Tuning the history token budget

`MAX_HISTORY_TOKENS` (ADR 0008) is a tuning knob, not a unit-test concern, so it has its own manual eval — run it whenever you change the budget:

```bash
python -m evals.history_budget          # trim sweep + one live contextualize call (~$0.0005)
python -m evals.history_budget --dry    # deterministic trim sweep only, no API call
```

It checks whether `contextualize` can still resolve an elliptical follow-up after trimming, across a sweep of budgets. This is deliberately an eval, not a test in `tests/` — a real-LLM resolution check is non-deterministic and doesn't belong in the CI gate.

### Model overrides

The router, contextualize, conversational, synthesiser, and grounding-check nodes — plus the background Semantic Memory extractor — each have an env var that controls which model they use. All are resolved through the provider-agnostic factory in `agent/llm_factory.py`: a `claude-*` name routes to Anthropic, `gemini-*` to Google, and anything else (including the `gpt-*` default) to OpenAI. The contextualize and conversational nodes and the memory extractor default to a cheaper mini-class model, since rewriting a query, replying to small talk, and extracting durable facts are lighter tasks than classification or synthesis. The grounding check is the one node that defaults to a Claude model, since it acts as an independent judge of whether the synthesiser's claims are supported by the cited sources. The conversational node is the one node that runs hot (`temperature=0.7`) so repeated greetings vary in wording; every other node runs at the factory default `temperature=0` for reproducible output.

| Env var | Node | Default |
|---|---|---|
| `ROUTER_MODEL` | router | `gpt-4.1` |
| `CONTEXTUALIZER_MODEL` | contextualize | `gpt-4.1-mini` |
| `CONVERSATIONAL_MODEL` | conversational | `gpt-4.1-mini` |
| `SYNTHESISER_MODEL` | synthesiser | `gpt-4.1` |
| `GROUNDING_MODEL` | grounding check | `claude-sonnet-4-6` |
| `MEMORY_EXTRACT_MODEL` | Semantic Memory extractor (background write path) | `gpt-4.1-mini` |

Override to `claude-haiku-4-5-20251001` (~3× cheaper than GPT-4.1) for fast pipeline-correctness signal without the GPT-4.1 default:

```bash
# both nodes on Haiku — cheapest local smoke run
ROUTER_MODEL=claude-haiku-4-5-20251001 SYNTHESISER_MODEL=claude-haiku-4-5-20251001 \
  python3 -m evals.run_evals --smoke

# router cheap, synthesiser on the production default — useful when tuning synthesiser prompts
ROUTER_MODEL=claude-haiku-4-5-20251001 python3 -m evals.run_evals --smoke
```

Shell exports take priority over `.env` values, so you can temporarily override your local default in a single command. Set them in `.env` for a persistent local default.

**When to trust Haiku eval results:** L1 assertions (regex, DB lookups, string matching) are LLM-free and fully reliable regardless of model. L2 judge signal is lower-fidelity when both nodes use Haiku — useful for detecting gross failures, but do not treat a passing Haiku eval as equivalent to a passing GPT-4.1 eval when tuning prompts. CI uses the `gpt-4.1` defaults (no `ROUTER_MODEL`/`SYNTHESISER_MODEL` set); `EVALS_JUDGE_MODEL` is set to `claude-haiku-4-5-20251001` for the L2 judge.

---

## Utility commands

```bash
python run.py --list-stubs          # list acts that failed step 2
python run.py --act 807             # manually re-scrape one act
python run.py --step 1 --dry-run    # print what would run without requests
tail -f scraper.log                 # follow pipeline logs
```
