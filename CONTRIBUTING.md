# Contributing

## Workflow

Do **not** commit directly to `main`. For every change — including small fixes and anything an AI agent makes on your behalf — create a new branch, push it, and open a pull request:

```bash
git switch -c <type>/<short-description>   # e.g. fix/citation-links-new-tab
# ...make changes, commit...
git push -u origin <branch>
gh pr create
```

Use a `<type>/` prefix that matches the change: `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`. `main` stays deployable; every change lands through a reviewable PR.

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
REFERENCE_GRAPH_ENABLED=off
REFERENCE_GRAPH_COMPARISON_ENABLED=off
FOLLOW_REFERENCES_ENABLED=off
# CORPUS_CDN_BASE_URL=https://statutes.example.com
```

With `LANGSMITH_TRACING=true`, every graph run traces to LangSmith. The query lifecycle also tags each run — `run_name=legal_query`, `source:api`/`source:eval`, active feature flags — attaches `user_id`/`thread_id` metadata, and posts the turn's quality signals as run **feedback** (`agent/observability.py`): `passed`, `num_violations`, `num_evidence_violations`, `retry_count`, `num_citations`, `fallback_delivered`, `escalated`, a categorical `query_type`. Feedback also includes numeric reference-follow counters — calls, skips/disabled/unavailable, edges considered/returned, target lookup outcomes, boundaries, fail-open occurrences — never provision text, evidence phrases, or query content. Fail-open, off the hot path: it never alters or delays a response. Leave `LANGSMITH_TRACING` unset to disable tracing and feedback entirely.

Optional flags. Toggles are off by default, and each accepts `1`, `true`, `yes`, or `on` — anything else leaves it off. `CORPUS_RETRIEVAL_MODE` defaults to `dual` and `RECEIPT_DELIVERY_MODE` to `auto`. Unset `CHECKPOINTER` means Postgres whenever `DATABASE_URL` is set.

- `CHECKPOINTER=memory` — forces the in-process `MemorySaver` + `InMemoryStore` instead of Postgres. Handy for local runs without a database. The test suite sets this automatically.
- `SEMANTIC_MEMORY_RECALL=on` — enables `recall`, so the synthesiser **reads** cross-thread **Semantic Memory** (ADR 0010). Off by default, fail-open.
- `SEMANTIC_MEMORY_EXTRACT=on` — background **write** path (`agent/memory/extractor.py`). Saves durable practitioner facts, including their own background (ADR 0012), after each turn. Off by default, fail-open, runs after the response is delivered. Turn both flags on to see `recall` surface facts written on earlier turns.
- `SEMANTIC_MEMORY_PRUNE=on` — background **maintenance** path (`agent/memory/pruner.py`). Consolidates duplicate profiles and near-duplicate topics. Evicts low-value topics by importance + recency, not TTL. Off by default, fail-open. Runs off the hot path, size-debounced. Never deletes the sole profile, never empties a namespace.
- `AGENTIC_RETRIEVAL=1` — swaps the deterministic `retriever` node for a `create_agent` ReAct loop that binds `search_statutes` / `lookup_section` and decides how to search (ADR 0013). Off by default, fail-open — any error or empty result falls back to the deterministic pgvector path. When on:
  - On an evidence violation the retry loop re-retrieves with feedback, not just re-drafts.
  - Retrieval tools stream `tool_call` SSE events into the PROCESS panel.
  - The eval `tool_selection` assertion (`expected_tool`) only runs with this flag on.
  - `RETRIEVAL_RECURSION_LIMIT` (default 6) bounds the ReAct loop.
- `CORPUS_RETRIEVAL_MODE=dual|verified|legacy` — `dual` (default) reads legacy rows plus provenance rows joined to the active Act/language mapping. `verified` reads active provenance only. `legacy` is the rollback path — it reads only rows with no provenance, so no shadow-ingested row is visible, activated or not.
- `RECEIPT_DELIVERY_MODE=auto|local|redirect|proxy` — `auto` (default) prefers verified local bytes. With none present it falls back to CDN objects whose length, content type, and `x-amz-meta-sha256` match the registry. `local` uses local bytes only and fails closed rather than reaching for the CDN. `redirect` and `proxy` skip local bytes and both need `CORPUS_CDN_BASE_URL`. An unrecognised value falls back to `auto`. Remote coordinate sidecars get hash-checked again after download.
- `REFERENCE_GRAPH_ENABLED=on` — exposes a **promoted**, independently validated statutory reference graph. Off by default; alone, builds/promotes/loads nothing.
- `REFERENCE_GRAPH_COMPARISON_ENABLED=on` — adds snapshot selection and one-hop comparison. Needs `REFERENCE_GRAPH_ENABLED=on` too. Independently off by default, fails closed without disabling Phase 1.
- `FOLLOW_REFERENCES_ENABLED=on` — adds `follow_references` to the **Retrieval Agent** only, so `AGENTIC_RETRIEVAL` must be on too. Independently off by default. Does not need `REFERENCE_GRAPH_ENABLED`: internal retrieval reads the promoted artifacts directly through `ReferenceGraphStore`, and `REFERENCE_GRAPH_ENABLED` governs public UI/API exposure instead. Flag off → model sees the original two tools, original prompt.
- `REFERENCE_GRAPH_ROOT` — read-only root of promoted artifacts, default `data/reference_graph`. Both the public graph flags and `follow_references` read it. Point it at an operator deployment's artifact root.

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_EVALS=1
```

### 3. Database schema

The normal corpus rollout command applies the additive migration automatically, after local assets pass verification. The migration creates immutable document/source/extraction tables, active and historical mappings, and nullable provenance columns on legacy `chunks` — it never infers provenance for existing rows. `python3 -m corpus migrate` stays available for database-only maintenance.

### 4. Build the knowledge base (one-time, ~1 hour)

```bash
python run.py --step all
python3 -m corpus rollout --dry-run
python3 -m corpus rollout
```

`corpus rollout` is the normal receipt setup and upgrade path — idempotent and resumable. Missing extraction assets get generated, the schema and registry get applied, only absent exact extractions are embedded and ingested, only successful verified runs get activated. A failure for one document is reported without activating it or blocking the rest. Embedding requests default to a US$1 hard cap per invocation; `--max-embedding-cost-usd` sets a different ceiling. Oversized chunks embed as token-bounded segments, pooled back to their single immutable chunk identity. `--document-id` limits a rollout; `--no-activate` prepares/ingests without switching retrieval.

All steps are idempotent. Step 3 re-observes authoritative PDF bytes to catch same-URL replacements; content/extraction identities prevent duplicate downstream work. Run steps individually if needed:

```bash
python run.py --step 1   # scrape Act listing pages (~1 min)
python run.py --step 2   # scrape Act detail pages (~45 min)
python run.py --step 3   # download PDFs (~18 min)
python run.py --step 4   # extract section-level chunks (~5 min)
python run.py --step 5   # embed + ingest into pgvector (~5 min, ~$0.15)
```

See [docs/data-pipeline.md](docs/data-pipeline.md) for what each step does and the JSON it produces.

### 5. Start the API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET http://localhost:8000/health`

Endpoints:
- `POST /query { query, thread_id, user_id? }` — run a turn (streams SSE)
- `POST /resume { thread_id, value, user_id? }` — answer a clarify interrupt, stream the resumed turn (ADR 0015)
- `POST /cancel { thread_id }` — barge-in: stop the in-flight turn for a thread (ADR 0014)
- `GET|HEAD /receipts/{document_id}/pdf` — serve, proxy, or redirect one verified immutable Receipt Document (ETag/304, ranges supported)
- `POST /receipts/{document_id}/locate { evidence_quote?, start_page, extraction_id? }` — locate one Evidence Span against the exact extraction sidecar
- `POST /receipts/telemetry` — accepts a small allowlisted, quote-free frontend failure event
- `GET /reference-graph/status?document_id?` — flag-gated graph status, independent of chat and health
- `GET /reference-graph/neighborhood?document_id=&focus_provision_id=` — one-hop direct incoming/outgoing edges only; no depth parameter
- `GET /reference-graph/snapshots?act_number=265&language=en` — promoted/audited snapshot selector data
- `GET /reference-graph/compare?base_document_id=&compare_document_id=&focus_provision_id=` — one Act/language pair, one focus, one one-hop overlay
- `GET /evals/coverage` — dataset coverage and best-effort dedicated-corpus status
- `POST /evals/run { subset }` — isolated eval run streamed as SSE; one active run at a time
- `POST /evals/cancel` — terminate the active eval subprocess
- `GET /evals/results` — last persisted eval report

> **Adding an LLM node?** Give it a **sync + async twin**: `x_node` (`.invoke`) and `ax_node` (`await .ainvoke`), sharing extracted prompt-building/post-processing. Register it as `RunnableCallable(x_node, ax_node, name=...)` in `graph.py` (see `synthesiser`/`recall`). The async twin lets a barge-in cancel the in-flight model request; the sync twin keeps the eval path (`run_query` → `graph.invoke`) working. Pure-Python nodes (e.g. `supervisor`) need no twin. A node's `except Exception` stays cancellation-safe as-is — `asyncio.CancelledError` is a `BaseException`, so a barge-in propagates through it instead of being swallowed.

> **Adding a human-in-the-loop pause?** Call LangGraph's `interrupt(payload)` inside a **dedicated, side-effect-free node** (see `agent/nodes/clarify.py`). The node re-runs from the top on resume — put nothing non-idempotent before the `interrupt()`. `_drive_query_stream` detects the `__interrupt__` update, emits an `interrupt` SSE event, and returns before the post-loop feedback/memory side effects — a paused turn writes nothing, like a barged-in one. Resume feeds `Command(resume=value)` on the same `thread_id`. No async twin needed: `interrupt()` isn't an awaited model call, so a barge-in has nothing to tear down there.

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). With `NEXT_PUBLIC_EVALS=1`, the standalone dashboard is at [http://localhost:3000/evals](http://localhost:3000/evals); without that build-time flag the route returns 404.

The Citation Receipt viewer uses `react-pdf` with the matching `pdfjs-dist` worker, bundled by Next.js from `pdfjs-dist/build/pdf.worker.min.mjs` — don't replace it with a runtime CDN. The viewer module is client-only, dynamically imported with SSR disabled.

### Statutory reference-graph operator workflow

The graph builds each consolidated Act 265 snapshot independently, from its exact registered PDF. The February 2023 graph keeps the historical alias `act-265-reprint-2023-6fec2f07`. Do **not** overwrite `data/pdfs/en/265.pdf`, rerun scraper steps 2–5, rebuild chunks, or change an active corpus mapping.

```bash
# Offline and network-free: strict chronological REPRINT/REPRINT ONLINE catalog
python3 -m reference_graph.cli catalog

# Explicit operator download; resumable and content-addressed, never activates retrieval
python3 -m reference_graph.cli acquire --download --snapshot-date 2023-09-02

# Candidate only: writes this immutable snapshot's isolated .work directory
python3 -m reference_graph.cli --document-id act-265-en-sha256-... build
python3 -m reference_graph.cli --document-id act-265-en-sha256-... verify-determinism
python3 -m reference_graph.cli --document-id act-265-en-sha256-... validate --candidate
python3 -m reference_graph.cli --document-id act-265-en-sha256-... audit
python3 -m reference_graph.cli --document-id act-265-en-sha256-... audit \
  --export-decisions audit-decisions.json
```

`acquire` without `--download` just catalogs, network-free. With `--download`, every result reports as one of: downloaded, already registered, unavailable, integrity failure, scanned/unparseable, or ready. A successful registration records, idempotently: exact source URL/date/type, SHA-256, byte size, page count, content-addressed local path, receipt route. Unreachable, corrupt, or unparseable sources stay explicit blockers — nothing gets guessed. Recorded dates describe observed snapshots, not exact effective dates.

Keep separate deterministic operator reports for the pilot and the older observations — the checked-in examples are `snapshot-acquisition-act-265.json` and `snapshot-acquisition-act-265-older.json`. Re-running acquisition must report `already_registered`, make no further request for locally verified bytes, leave `active_documents` unchanged.

Each build writes `.work/build-report.json`. A registered PDF whose text layout can't be parsed produces a persistent `blocked` report — failure stage and error class — instead of guessed provisions.

Every candidate decision must be checked against that snapshot's exact PDF receipt. A complete JSON decision mapping with an audit note per candidate ID is mandatory:

```json
{
  "decisions": {
    "candidate:...": {
      "decision": "approved",
      "audit_note": "Checked against the exact receipt and page rectangles."
    }
  }
}
```

Only after the human gate:

```bash
python3 -m reference_graph.cli --document-id act-265-en-sha256-... audit --decisions audit-decisions.json
python3 -m reference_graph.cli --document-id act-265-en-sha256-... promote
python3 -m reference_graph.cli --document-id act-265-en-sha256-... validate
python3 -m reference_graph.cli migrate
python3 -m reference_graph.cli --document-id act-265-en-sha256-... load
python3 -m reference_graph.cli --document-id act-265-en-sha256-... verify-db
```

Rejected candidates stay in the promoted unresolved/audit artifacts. Promotion, loading, `/snapshots`, and `/compare` reject candidate-only or incomplete-audit data. Migrations `0001_reference_graph.sql` and `0002_reference_graph_artifact_identity.sql` are additive, never touch `chunks` — the database is an idempotent verified mirror, the API always reads promoted artifacts.

Roll out code, migrations, immutable assets, and approved artifacts with comparison still off. Load and verify only audited snapshots, verify February-versus-September in staging, then enable comparison separately. To roll back: turn `REFERENCE_GRAPH_COMPARISON_ENABLED` off first — Phase 1 neighborhoods, receipts, and chat keep working. Wrong graph data → reload the prior approved artifact. Never enable either flag just because acquisition or a candidate build succeeded.

Phase 3 ships with `FOLLOW_REFERENCES_ENABLED=off`. Before enabling: all focused positive/negative selection checks, exact provenance/citation tests, the full regression suite, already-promoted/audited graph artifacts, explicit operator approval — all required. It consumes published `edges.json` records only; changing graph data or published edges needs the manual artifact audit again.

The internal follow contract stays narrow:

- Establish a unique exact anchor through existing search/lookup first — legacy/unversioned chunks never map to a newer graph snapshot.
- One follow operation per retrieval run, one direct outgoing/incoming scope, deterministic truncation, at most five edges.
- A section's scope is its audited subsection/paragraph edges — never traverse a target for another hop.
- Retrieve same-Act target text only from the anchor's exact document/extraction. Retrieve any cross-Act target independently, with its own provenance and no source-snapshot as-of claim.
- Report boundary targets but never expand them. Never expose unresolved candidates or use graph provision/evidence text as a normal RAG citation source.
- Fail open on absent/malformed artifacts, snapshot mismatch, target lookup failure, or telemetry failure.

Rollback is immediate: set `FOLLOW_REFERENCES_ENABLED=off`, restart workers, and the cached disabled agent variant exposes only `search_statutes` and `lookup_section`. No need to disable public graph features, delete graph/database data, change active corpus mappings, or touch Phase 1/2 artifacts. Code rollback, if needed, reverts Phase 3 only.

### Citation Receipt assets and verification

`data/pdfs/manifest.json` is generated, never hand-edited. A changed PDF hash creates a new staged `document_id`; the previous bytes stay addressable, and the active mapping doesn't move until the new extraction is embedded and explicitly activated. See [docs/data-pipeline.md](docs/data-pipeline.md) (Step 3) for how a PDF gets registered, and [docs/corpus-receipts.md](docs/corpus-receipts.md) for the full identity lifecycle.

Corpus lifecycle commands:

```bash
# Normal end-to-end path (safe to rerun)
python3 -m corpus rollout --dry-run
python3 -m corpus rollout

# Granular recovery and production-storage operations
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

The CLI loads the repository `.env` — no need to manually export `DATABASE_URL`. Preview `rollout` before its first run against a database; live execution performs embedding calls and changes active retrieval mappings. Live upload uses optional `boto3`, not an application dependency. Configure R2 bucket retention/object-lock policy and custom-domain CORS outside this repository: allow `GET`, `HEAD`, `OPTIONS`; allow request headers `Range`, `If-None-Match`; expose `ETag`, `Accept-Ranges`, `Content-Range`, `Content-Length`.

Run all automated checks from the repository root and frontend respectively:

```bash
python3 -m pytest -q
LANGSMITH_TRACING=false python3 -m pytest -q \
  tests/test_reference_following.py \
  tests/test_reference_follow_evals.py \
  tests/test_agentic_retriever.py \
  tests/test_retrieval_tools.py \
  tests/test_retriever_exact_lookup.py \
  tests/test_synthesiser_language.py \
  tests/test_observability.py \
  tests/test_assertions.py
python3 -m evals.validate_dataset --dataset evals/reference_follow_dataset.json
cd frontend
npm run lint
npm test
npm run build
```

`npm test` uses Vitest in non-watch CI mode. Receipt interaction tests mock the canvas renderer, assert state/DOM behavior; geometry is verified against real pilot PDFs separately.

Local endpoint smoke against the saved Act 56 alias (historical aliases stay valid):

```bash
curl -sS http://localhost:8000/receipts/act-56-reprint-2017-c11400ad/pdf -o /tmp/act-56-receipt.pdf
shasum -a 256 /tmp/act-56-receipt.pdf
curl -sS -X POST http://localhost:8000/receipts/act-56-reprint-2017-c11400ad/locate \
  -H "Content-Type: application/json" \
  -d '{"evidence_quote":"In any criminal or civil proceeding","start_page":72,"extraction_id":"extraction-sha256-b4c94c5a446bcc44df76324ff254d096dba1ccea6fbe190784d9014d8c0ef81b"}'
```

Expected SHA-256: `c11400ad1b0a9941919d7328c60fc1c2b49fb2788671bf9697c2923364c96d07`. The locate response should read `matched` on physical page 72. Run the five questions in `docs/pdf-receipt-view-design.md` for the manual local/deployed visual matrix before release.

---

## Running Evals

Requires `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and a dedicated eval database. Never point dashboard evals or the destructive seed command at the app's development corpus.

Create (if needed) and seed the conventional `ai_legal_tool_evals` database with one command. This embeds the curated sections and clears only the database named in `EVALS_DATABASE_URL`:

```bash
EVALS_DATABASE_URL=postgresql://user@/ai_legal_tool_evals?host=/path/to/pg/socket \
  python3 -m evals.setup_eval_db
```

Keep `EVALS_DATABASE_URL` in the API's `.env`. Dashboard subprocesses remap it to `DATABASE_URL` and force `CHECKPOINTER=memory`, so the eval database only needs the `chunks` table. Corpus staleness gets checked before every dashboard run; missing required sections → rerun the setup command. Seeding is deliberately never an HTTP or dashboard action.

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

# Phase 3 selection/citation gate (live model calls; requires explicit authorized egress
# and a dedicated production-like corpus with active exact Act 265 provenance)
AGENTIC_RETRIEVAL=1 FOLLOW_REFERENCES_ENABLED=on \
  DATABASE_URL="$PHASE3_EVAL_DATABASE_URL" \
  python3 -m evals.run_evals --dataset evals/reference_follow_dataset.json --mode full
```

`run_evals` also supports `--smoke`, `--category`, `--scenario`, `--case-id`, and machine-readable `--jsonl` output. Human-readable output stays the default; results write to `evals/results.json` by default. Phase 3 cases add ordered `expected_tool_sequence`, `forbidden_tools`, `max_tool_calls`, and executed `expected_reference_direction` assertions — existing `expected_tool` semantics unchanged. The dedicated dataset fails fast unless both required flags are on. Its database must be a dedicated production-like staging/eval corpus, with an active exact Act 265 document/extraction matching an already-promoted graph — the tiny default eval seed has legacy-shaped chunks, intentionally insufficient for this provenance gate. Don't point the live gate at the application development database. A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered via `workflow_dispatch`) runs the 10-case smoke set against the production model defaults and posts the judge pass rate and key L1 metrics as a PR comment; fails if the judge pass rate drops below 80%.

### Tuning the history token budget

`MAX_HISTORY_TOKENS` (ADR 0008) is a tuning knob, not a unit-test concern — it has its own manual eval, run it whenever you change the budget:

```bash
python -m evals.history_budget          # trim sweep + one live contextualize call (~$0.0005)
python -m evals.history_budget --dry    # deterministic trim sweep only, no API call
```

It checks whether `contextualize` can still resolve an elliptical follow-up after trimming, across a sweep of budgets. Deliberately an eval, not a test in `tests/` — a real-LLM resolution check is non-deterministic and doesn't belong in the CI gate.

### Model overrides

Each of the router, contextualize, conversational, synthesiser, and grounding-check nodes — plus the agentic retriever and the background Semantic Memory extractor — has its own env var controlling which model it uses. All resolve through the provider-agnostic factory in `agent/llm_factory.py`: `claude-*` → Anthropic, `gemini-*` → Google, anything else (including the `gpt-*` default) → OpenAI. Contextualize, conversational, and the memory extractor default to a cheaper mini-class model — rewriting a query, replying to small talk, and extracting durable facts are lighter tasks than classification or synthesis. The grounding check defaults to a Claude model, since it acts as an independent judge of whether the synthesiser's claims are supported by the cited sources. The conversational node is the one that runs hot (`temperature=0.7`), so repeated greetings vary in wording; every other node runs at the factory default `temperature=0` for reproducible output.

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

Shell exports beat `.env` values, so you can override your local default in a single command. Set them in `.env` for a persistent local default.

**When to trust Haiku eval results:** L1 assertions (regex, DB lookups, string matching) are LLM-free, fully reliable regardless of model. L2 judge signal gets lower-fidelity when both nodes use Haiku — useful for catching gross failures, but don't treat a passing Haiku eval as equivalent to a passing GPT-4.1 eval when tuning prompts. CI uses the `gpt-4.1` defaults (no `ROUTER_MODEL`/`SYNTHESISER_MODEL` set); `EVALS_JUDGE_MODEL` is set to `claude-haiku-4-5-20251001` for the L2 judge.

---

## Utility commands

```bash
python run.py --list-stubs          # list acts that failed step 2
python run.py --act 807             # manually re-scrape one act
python run.py --step 1 --dry-run    # print what would run without requests
tail -f scraper.log                 # follow pipeline logs
```
