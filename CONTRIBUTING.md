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
EVALS_DATABASE_URL=postgresql://user@/ai_legal_tool_evals?host=/path/to/pg/socket
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=...
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=ai-legal-tool
CORPUS_RETRIEVAL_MODE=dual
CORPUS_MANIFEST_PATH=data/pdfs/manifest.json
CORPUS_LOCAL_ROOT=data/pdfs
CORPUS_SIDECAR_ROOT=data/corpus/sidecars
RECEIPT_DELIVERY_MODE=auto
# CORPUS_CDN_BASE_URL=https://statutes.example.com
```

With `LANGSMITH_TRACING=true`, every graph run is traced to LangSmith. The query
lifecycle also tags each run (`run_name=legal_query`; `source:api`/`source:eval`;
active feature flags) and attaches `user_id`/`thread_id` metadata, and posts the
turn's quality signals as run **feedback** — `passed`, `num_violations`,
`num_evidence_violations`, `retry_count`, `num_citations`, `fallback_delivered`,
`escalated`, and a categorical `query_type` (`agent/observability.py`). Feedback
is fail-open and off the hot path — it never alters or delays a response. Leave
`LANGSMITH_TRACING` unset to disable tracing and feedback entirely.

Optional flags (both default off / to Postgres):

- `CHECKPOINTER=memory` — force the in-process `MemorySaver` + `InMemoryStore` instead of Postgres (handy for local runs without a database; the test suite sets this automatically).
- `SEMANTIC_MEMORY_RECALL=on` — enable the `recall` node so the synthesiser **reads** cross-thread **Semantic Memory** (ADR 0010). Off by default, fail-open.
- `SEMANTIC_MEMORY_EXTRACT=on` — enable the background **write** path (`agent/memory/extractor.py`) that extracts durable practitioner facts (including the practitioner's own background — ADR 0012) after a legal or conversational turn and upserts them into the store. Off by default, fail-open, and runs off the hot path (after the response is delivered). Turn both flags on to see recall surface facts written on earlier turns.
- `SEMANTIC_MEMORY_PRUNE=on` — enable the background **maintenance** path (`agent/memory/pruner.py`) that consolidates duplicate profiles / near-duplicate topics and evicts low-value topics by importance+recency (not TTL). Off by default, fail-open, off the hot path, size-debounced, and conservative (never deletes the sole profile or empties a namespace).
- `AGENTIC_RETRIEVAL=on` — swap the deterministic `retriever` node for a `create_react_agent` that binds the `search_statutes` / `lookup_section` tools and decides how to search (ADR 0013). Off by default, fail-open (any error or empty result falls back to the deterministic pgvector path). With it on, the retry loop also re-retrieves with feedback on an evidence-shaped violation instead of only re-drafting, and the retrieval tools stream `tool_call` SSE events into the PROCESS panel. The eval `tool_selection` assertion (dataset `expected_tool`) only activates when this flag is on. `RETRIEVAL_RECURSION_LIMIT` (default 6) bounds the ReAct loop.
- `CORPUS_RETRIEVAL_MODE=dual|verified|legacy` — `dual` (default) reads legacy rows plus only provenance rows joined to the active Act/language mapping; `verified` reads active provenance only; `legacy` is the rollback path and excludes shadow rows.
- `RECEIPT_DELIVERY_MODE=auto|local|redirect|proxy` — `auto` uses verified local bytes when present, otherwise CDN objects whose length, content type, and `x-amz-meta-sha256` match the registry. Remote coordinate sidecars are hash-checked again after download. `redirect` and `proxy` require `CORPUS_CDN_BASE_URL`.

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_EVALS=1
```

### 3. Database schema

```bash
python3 -m corpus migrate --dry-run
python3 -m corpus migrate
```

The additive migration creates immutable document/source/extraction tables, active and historical mappings, and nullable provenance columns on legacy `chunks`. It does not infer provenance for existing rows.

### 4. Build the knowledge base (one-time, ~1 hour)

```bash
python run.py --step all
```

All steps are idempotent. Step 3 re-observes authoritative PDF bytes to detect same-URL replacements, while content/extraction identities prevent duplicate downstream work. Run steps individually if needed:

```bash
python run.py --step 1   # scrape Act listing pages (~1 min)
python run.py --step 2   # scrape Act detail pages (~45 min)
python run.py --step 3   # download PDFs (~18 min)
python run.py --step 4   # extract section-level chunks (~5 min)
python run.py --step 5   # embed + ingest into pgvector (~5 min, ~$0.15)
```

See [docs/data-pipeline.md](docs/data-pipeline.md) for what each step does in detail and the JSON it produces.

### 5. Start the API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET http://localhost:8000/health`

Endpoints:
- `POST /query { query, thread_id, user_id? }` — run a turn (streams SSE)
- `POST /resume { thread_id, value, user_id? }` — answer a clarify interrupt and stream the resumed turn (see ADR 0015)
- `POST /cancel { thread_id }` — barge-in: stop the in-flight turn for a thread (see ADR 0014)
- `GET|HEAD /receipts/{document_id}/pdf` — serve, proxy, or redirect one verified immutable Receipt Document (ETag/304 and ranges supported)
- `POST /receipts/{document_id}/locate { evidence_quote?, start_page, extraction_id? }` — locate one Evidence Span against the exact extraction sidecar
- `GET /evals/coverage` — dataset coverage and best-effort dedicated-corpus status
- `POST /evals/run { subset }` — isolated eval run streamed as SSE; one active run at a time
- `POST /evals/cancel` — terminate the active eval subprocess
- `GET /evals/results` — last persisted eval report

> **Adding an LLM node?** Give it a **sync + async twin** — `x_node` (calls `.invoke`) and `ax_node` (`await .ainvoke`), sharing extracted prompt-building/post-processing — and register it as `RunnableCallable(x_node, ax_node, name=...)` in `graph.py` (see `synthesiser`/`recall`). The async twin lets a barge-in cancel the in-flight model request; the sync twin keeps the eval path (`run_query` → `graph.invoke`) working. Pure-Python nodes (e.g. `supervisor`) need no twin. A node's `except Exception` stays cancellation-safe as-is — `asyncio.CancelledError` is a `BaseException`, so a barge-in propagates through it instead of being swallowed.

> **Adding a human-in-the-loop pause?** Call LangGraph's `interrupt(payload)` inside a **dedicated, side-effect-free node** (see `agent/nodes/clarify.py`). The node re-runs from the top on resume, so put nothing non-idempotent before the `interrupt()`. `_drive_query_stream` detects the `__interrupt__` update, emits an `interrupt` SSE event, and returns *before* the post-loop feedback/memory side effects — a paused turn writes nothing, exactly like a barged-in one. Resume feeds `Command(resume=value)` on the same `thread_id`. No async twin is needed: `interrupt()` is not an awaited model call, so a barge-in has nothing to tear down there.

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). With `NEXT_PUBLIC_EVALS=1`, the standalone developer dashboard is at [http://localhost:3000/evals](http://localhost:3000/evals); without that build-time flag the route returns 404.

The Citation Receipt viewer uses `react-pdf` with the matching `pdfjs-dist` worker bundled by Next.js from `pdfjs-dist/build/pdf.worker.min.mjs`; do not replace it with a runtime CDN. The viewer module is client-only and is dynamically imported with SSR disabled.

### Citation Receipt assets and verification

`data/pdfs/manifest.json` is generated, never hand-edited. A changed PDF hash creates a new staged `document_id`; the previous bytes remain addressable and the active mapping does not move until the new extraction is embedded and explicitly activated. Step 3 accepts reprints only, re-observes their bytes even when the source URL is unchanged, validates them, and registers them under a content-addressed local/object key. Amendment-only files are individual coverage blockers, never base Acts.

Corpus lifecycle commands:

```bash
python3 -m corpus generate-manifest \
  --pdf-root /path/to/data/pdfs \
  --existing-manifest data/pdfs/manifest.json
python3 -m corpus shadow-extract --pdf-root /path/to/data/pdfs
python3 -m corpus validate --pdf-root /path/to/data/pdfs \
  --sidecar-root data/corpus/sidecars --scope full --deep --format json
python3 -m corpus register --dry-run
python3 -m corpus ingest --bundle data/corpus/extractions/<extraction>.chunks.json \
  --extraction-id <extraction-id> --dry-run
python3 -m corpus activate --document-id <document-id> \
  --extraction-id <extraction-id> --dry-run
python3 -m corpus rollback --act-number 574 --language en --dry-run
python3 -m corpus upload --pdf-root /path/to/data/pdfs \
  --sidecar-root /path/to/full/sidecars --bucket <r2-bucket> \
  --endpoint-url https://<account>.r2.cloudflarestorage.com --dry-run
python3 -m corpus validate --cdn-base-url https://statutes.example.com \
  --scope full --deep --format json
```

Remove `--dry-run` only with reviewed database/object-store credentials. Live upload uses optional `boto3`; it is not an application dependency. Configure R2 bucket retention/object-lock policy and custom-domain CORS (`GET`, `HEAD`, `OPTIONS`; request headers `Range`, `If-None-Match`; expose `ETag`, `Accept-Ranges`, `Content-Range`, `Content-Length`) outside this repository.

Run all automated checks from the repository root and frontend respectively:

```bash
python3 -m pytest -q
cd frontend
npm run lint
npm test
npm run build
```

`npm test` uses Vitest in non-watch CI mode. Receipt interaction tests mock the canvas renderer and assert state/DOM behavior; geometry is verified against real pilot PDFs separately.

Local endpoint smoke against the saved Act 56 alias (historical aliases remain valid):

```bash
curl -sS http://localhost:8000/receipts/act-56-reprint-2017-c11400ad/pdf -o /tmp/act-56-receipt.pdf
shasum -a 256 /tmp/act-56-receipt.pdf
curl -sS -X POST http://localhost:8000/receipts/act-56-reprint-2017-c11400ad/locate \
  -H "Content-Type: application/json" \
  -d '{"evidence_quote":"In any criminal or civil proceeding","start_page":72,"extraction_id":"extraction-sha256-b4c94c5a446bcc44df76324ff254d096dba1ccea6fbe190784d9014d8c0ef81b"}'
```

The expected SHA-256 is `c11400ad1b0a9941919d7328c60fc1c2b49fb2788671bf9697c2923364c96d07`; the locate response should be `matched` on physical page 72. Run the five questions in `docs/pdf-receipt-view-design.md` for the manual local/deployed visual matrix before release.

---

## Running Evals

Requires `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and a dedicated eval database. Never point dashboard evals or the destructive seed command at the app's development corpus.

Create (if needed) and seed the conventional `ai_legal_tool_evals` database with one command. This embeds the curated sections and clears only the database named in `EVALS_DATABASE_URL`:

```bash
EVALS_DATABASE_URL=postgresql://user@/ai_legal_tool_evals?host=/path/to/pg/socket \
  python3 -m evals.setup_eval_db
```

Keep `EVALS_DATABASE_URL` in the API's `.env`. Dashboard subprocesses remap it to `DATABASE_URL` and force `CHECKPOINTER=memory`, so the eval database needs only the `chunks` table. Corpus staleness is checked before every dashboard run; if required sections are missing, rerun the setup command. Seeding is deliberately never available as an HTTP or dashboard action.

For direct CLI runs, explicitly point `DATABASE_URL` at the same eval database:

```bash
# generate human-review checklist
python3 -m evals.validate_dataset --format markdown --output evals/review-checklist.md

# quick smoke test (5 cases)
DATABASE_URL="$EVALS_DATABASE_URL" python3 -m evals.run_evals --mode full --limit 5

# full suite
DATABASE_URL="$EVALS_DATABASE_URL" python3 -m evals.run_evals --mode full

# retriever + synthesiser only (no supervisor), used for before/after comparison
DATABASE_URL="$EVALS_DATABASE_URL" python3 -m evals.run_evals --mode baseline
```

`run_evals` also supports `--smoke`, `--category`, `--scenario`, `--case-id`, and machine-readable `--jsonl` output. Human-readable output remains the default. Results are written to `evals/results.json` by default. A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered via `workflow_dispatch`) runs the 10-case smoke set against the production model defaults and posts the judge pass rate and key L1 metrics as a PR comment; it fails if the judge pass rate drops below 80%.

### Tuning the history token budget

`MAX_HISTORY_TOKENS` (ADR 0008) is a tuning knob, not a unit-test concern, so it has its own manual eval — run it whenever you change the budget:

```bash
python -m evals.history_budget          # trim sweep + one live contextualize call (~$0.0005)
python -m evals.history_budget --dry    # deterministic trim sweep only, no API call
```

It checks whether `contextualize` can still resolve an elliptical follow-up after trimming, across a sweep of budgets. This is deliberately an eval, not a test in `tests/` — a real-LLM resolution check is non-deterministic and doesn't belong in the CI gate.

### Model overrides

The router, contextualize, conversational, synthesiser, and grounding-check nodes — plus the agentic retriever and the background Semantic Memory extractor — each have an env var that controls which model they use. All are resolved through the provider-agnostic factory in `agent/llm_factory.py`: a `claude-*` name routes to Anthropic, `gemini-*` to Google, and anything else (including the `gpt-*` default) to OpenAI. The contextualize and conversational nodes and the memory extractor default to a cheaper mini-class model, since rewriting a query, replying to small talk, and extracting durable facts are lighter tasks than classification or synthesis. The grounding check is the one node that defaults to a Claude model, since it acts as an independent judge of whether the synthesiser's claims are supported by the cited sources. The conversational node is the one node that runs hot (`temperature=0.7`) so repeated greetings vary in wording; every other node runs at the factory default `temperature=0` for reproducible output.

| Env var | Node | Default |
|---|---|---|
| `ROUTER_MODEL` | router | `gpt-4.1` |
| `CONTEXTUALIZER_MODEL` | contextualize | `gpt-4.1-mini` |
| `CONVERSATIONAL_MODEL` | conversational | `gpt-4.1-mini` |
| `SYNTHESISER_MODEL` | synthesiser | `gpt-4.1` |
| `GROUNDING_MODEL` | grounding check | `claude-sonnet-4-6` |
| `RETRIEVAL_AGENT_MODEL` | agentic retriever ReAct agent (`AGENTIC_RETRIEVAL` on) | `gpt-4.1` |
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
