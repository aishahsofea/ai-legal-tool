# Malaysian Legal Research AI Assistant

> Ask about Malaysian legislation in English, Bahasa Malaysia, or a mix of both — and get an answer grounded in the actual statute text, with citations that deep-link to the exact page of the official PDF.

Malaysian practitioners, pupils and paralegals check statutes on the AGC portal, where Acts are PDFs and some are scans. The PDF reprint of an Act can be out of date once an amendment passes. This tool finds the section, cites it to the page, and labels each Act repealed, superseded, current as indexed, or unknown.

A LangGraph agent that answers over a pgvector corpus of section-level chunks scraped from the
[AGC portal](https://lom.agc.gov.my). It cites every legal claim. It never gives legal advice.
For anything client-specific, it hands off to a human lawyer.

**Stack:**

- LangGraph
- FastAPI (Railway)
- Next.js (Vercel)
- Postgres + pgvector (Supabase)
- PDFs on Cloudflare R2
- NVIDIA Nemotron on Nebius Token Factory
- OpenAI `text-embedding-3-small`
- Tavily: web search for [Commentary Notes](CONTEXT.md#language) (needs `TAVILY_API_KEY`)

How production is wired: [Deployment](docs/deployment.md).

The hosted demo runs every chat model on open-weights NVIDIA Nemotron, served by Nebius Token Factory. Nemotron-3.5-Lightning (30B) handles the light steps: classifying the query, rewriting follow-ups, replying to small talk, and extracting memories. Nemotron-3-Ultra (550B) searches the statutes as an agent, writes the cited answer, and checks it against the sources (the grounding check). The chat UI's PROCESS panel names the model behind each step. Measured over 5 three-turn threads, Lightning is about 3x cheaper per light step, but light steps are a small share of the cost, so the total saving was within noise.

Out of the box, the code uses the GPT-4.1 family, plus Claude for the grounding check. Nemotron comes from config: `CHAT_BASE_URL` points the chat models at Nebius, or at any OpenAI-compatible endpoint. Any step can also run on a Claude or Gemini model. [Model overrides](CONTRIBUTING.md#model-overrides) has the default and the setting for every step and for embeddings. Chat models go through `agent/llm_factory.py` and embeddings through `agent/embeddings.py`. Claude runs the eval judge.

## Highlights

- Every response cites Act + section + PDF page — a schedule provision cites its path instead (e.g. `sched.2/para.1`, see [CONTEXT.md](CONTEXT.md#language)). A verified chunk opens an in-app **Citation Receipt**; otherwise the citation falls back to the Official Source Link.
- Bilingual: English, Bahasa Malaysia, and code-switched queries, retrieving EN and BM chunks together.
- A supervisor blocks legal-advice phrasing, requires a disclaimer, and escalates client-specific questions to a human — before retrieval even starts.
- Agentic retrieval (optional): a ReAct agent picks semantic search or exact-section lookup, and re-searches on weak hits. Falls back to a deterministic pgvector path — never retrieves less than that path would.
- Selective reference following (optional): one bounded hop through the promoted reference graph, only for explicit reference questions, only after an exact anchor is retrieved. Off by default, invisible when off, fails open on graph errors.
- Memory: server-side per-thread history, plus an optional cross-thread semantic memory for a practitioner's preferences and recurring topics.
- Evaluated: a hand-validated benchmark, deterministic checks (L1) plus an LLM judge (L2), gated in CI.

## Quick start

Full setup — env vars, database, frontend, evals — lives in [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

```bash
cp .env.example .env                         # then fill in its first three values
pip3 install -r requirements.txt
python run.py --step all                     # build the knowledge base (~1h, one-time, resumable)
python3 -m corpus rollout --dry-run           # preview receipt migration/ingestion/activation
python3 -m corpus rollout                     # finish every verified receipt, safely resumable
uvicorn api.main:app --port 8000 --reload    # start the API
```

Then `cd frontend && npm install && npm run dev` for the chat UI at `localhost:3000`. The workspace needs a GitHub sign-in, so set up Supabase Auth first ([CONTRIBUTING.md](CONTRIBUTING.md#sign-in-supabase-auth)).

## How it works

Each query carries a `thread_id` and runs through this LangGraph graph before the answer reaches the user:

```text
query + thread_id (EN / BM / mixed)
  → start_turn           load thread history, reset per-turn scratch state
  → router               classify the query: Jev classifier first, LLM fallback
  → contextualize        rewrite an elliptical follow-up into a standalone query
  → retriever            pgvector section search, or a ReAct agent when AGENTIC_RETRIEVAL is on
  → recall               surface saved practitioner preferences as framing hints (optional)
  → synthesiser          draft the answer with citations (act, section, page deep-link)
  → citation_validator   reject citations absent from the retrieved sources
  → grounding_check      flag unsupported claims, keep only verified Evidence Spans
  → currency_check       label each cited Act repealed, superseded, current_as_indexed or unknown
  → supervisor           enforce policy, retry once on a violation
  → record_turn          append the turn to checkpointed history
```

Full node, edge and state map: [CONTRIBUTING.md](CONTRIBUTING.md#graph-map).

<details>
<summary><strong>Short-circuits &amp; retry routing</strong></summary>

Three router outcomes end the turn early:

- **escalate**: a client-specific query ("am I liable…", "my client…") goes through `escalate` straight to `record_turn` with a fixed message referring the user to a qualified Malaysian lawyer.
- **conversational**: an unambiguously non-legal message (greeting, name, thanks, "what can you do?") gets a short, warm reply. It passes through `recall_conversational`, a second copy of `recall`, then `conversational`. No retrieval, no supervisor, no citations, no disclaimer.
- **clarify**: an un-actionable legal query (a section with no Act) routes to the `clarify` node. It pauses the graph with LangGraph's `interrupt()`, at most once per turn, and asks the user a question. The graph resumes on `POST /resume`. See ADR 0015.

`supervisor` allows one retry (`MAX_RETRIES=1`). The retry re-runs the checks, and its path depends on what went wrong:

- **Policy or phrasing violation** (advice phrase, missing disclaimer): `increment_retry` loops back to `synthesiser`, which re-drafts against the same chunks.
- **Evidence violation** (an uncited claim, or a citation not in the sources):
  - `AGENTIC_RETRIEVAL` on: `retry_retrieve` re-runs the retrieval agent with feedback about the gap.
  - `AGENTIC_RETRIEVAL` off: re-drafts via `increment_retry`, because the deterministic retriever would only repeat the same search.

If any violation remains after the retry, including an evidence gap that survives re-retrieval, the turn fails closed: `record_turn` sends `FINAL_FAILURE_RESPONSE` (`agent/query_policy.py`) instead of the draft.

</details>

The ReAct retriever calls `search_statutes` and `lookup_section`. It may also follow one cross-reference to another provision, a selective, optional [Reference Follow Operation](CONTEXT.md#reference-graph). [Evidence Span](CONTEXT.md#provenance-and-citation-receipts) and [Currency Label](CONTEXT.md#currency-and-timeline) are defined in CONTEXT.md.

[CONTEXT.md](CONTEXT.md) defines the domain model and supervisor rules. Design decisions live in `docs/adr/`: ADR 0008 history budget, 0010/0012 semantic memory, 0013 agentic retrieval, 0014 barge-in, 0015 clarify interrupt.

## API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET /health`. The query endpoint streams Server-Sent Events:

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What does Section 17 of the Evidence Act say about admissions?", "thread_id": "demo-1"}'
```

```text
data: {"type": "status",    "message": "Classifying query..."}
data: {"type": "tool_call", "name": "search_statutes", "summary": "Searching statutes: “…”"}
data: {"type": "status",    "message": "Searching Malaysian Acts..."}
data: {"type": "node",      "name": "router", "model": "gpt-4.1", "duration_ms": 412}
data: {"type": "status",    "message": "Drafting response..."}
data: {"type": "status",    "message": "Checking policy compliance..."}
data: {"type": "response",  "content": "...", "citations": [...], "violations": []}
data: {"type": "done"}
```

- **`response`** carries `content`, `violations`, and `citations`. Each citation has `act_number`, `act_title`, `section_number`, `pdf_url` (the official AGC fallback), and `page_number` — a schedule provision has `path` instead of `section_number` (e.g. `sched.2/para.1`, see [CONTEXT.md](CONTEXT.md#language)). A provenance-backed citation also has `receipt: { document_id, extraction_id, evidence: [{ claim, quote }] }`; legacy/unavailable rows omit it. It also carries `commentary` (a list of **Commentary Notes**) and `currency_labels` (a list of **Currency Labels**) — see [CONTEXT.md](CONTEXT.md#language) for both. Each is present only when the turn found at least one, omitted (not `[]`) the rest of the time. Flags: [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables).
- **Auth.** `/query`, `/resume`, `/cancel` and `/threads` (including `DELETE`) need `Authorization: Bearer <Supabase access token>`. No token: 401. Another user's `thread_id`: 404. Details and setup: [CONTRIBUTING.md](CONTRIBUTING.md#sign-in-supabase-auth).
- **CORS.** Browser origins come from `FRONTEND_ORIGIN`. See [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables).
- **`tool_call`** (`name`, `summary`) fires only on the agentic-retrieval path, once per retrieval tool call; the frontend renders these in the collapsible PROCESS panel.
- **`node`** (`name`, `model`, `duration_ms`) fires once per model call, in execution order. A retry emits a second synthesiser row, and a node that short-circuits before its model emits none. The PROCESS panel lists them under MODELS, so a run split across providers says which model answered where. Never carries prompt text, user content, or token counts.
- **`status`** tracks the phase and reflects short-circuits: `"Resolving follow-up..."`, `"Refining response..."` (a retry), `"Escalating to human lawyer..."`, or `"Responding..."` (conversational).
- **`interrupt`** (`question`, `interrupt_id`) fires when the graph pauses to ask the user a clarifying question (see below). The stream ends there — no `response` follows until you resume.

**Clarification (graph asks you a question):** an un-actionable query — most often a section number with no Act ("what does section 5 say?") — routes to a `clarify` node that calls LangGraph's `interrupt()`. The turn suspends, the `/query` stream emits an `interrupt` event with the `question`, and the graph waits. Answer it with `POST /resume { thread_id, value }`, which streams the continuation of the same turn:

```bash
curl -N -X POST http://localhost:8000/resume \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "demo-1", "value": "the Contracts Act 1950"}'
```

The answer merges with the original query into one self-contained query, so retrieval sees the full intent, not just the answer. History records the single merged turn. This is a graph-initiated pause, distinct from the user-initiated barge-in below. See ADR 0015.

**Barge-in (stop a running turn):** `POST /cancel { thread_id }` cancels the in-flight turn for a thread — the Stop button / Esc. It aborts the live model request; the `/query` SSE stream for that thread ends on its own. A cancelled turn writes nothing — no `response`, no history, no memory — so the next prompt starts clean. Returns `{"status": "cancelled"}` or `{"status": "no_active_run"}`; idempotent. One active run per `thread_id`, so a new `POST /query` on the same thread also supersedes any in-flight run — no explicit cancel needed to change your mind. See ADR 0014.

### Citation Receipt API

`data/pdfs/manifest.json` is a deterministic, corpus-wide registry of every PDF's identity, version, and language. The checked-in audit lists registered, ready, and blocked counts, with blocked reasons; it lives in [docs/corpus-receipts.md](docs/corpus-receipts.md). How to run it locally is in [CONTRIBUTING.md](CONTRIBUTING.md#4-build-the-knowledge-base-one-time-1-hour). Only the five pilot PDFs are tracked in git; the PDFs and highlight coordinates behind receipts live in Cloudflare R2, and upload and delivery are in [CONTRIBUTING.md](CONTRIBUTING.md#citation-receipt-assets-and-verification).

- `GET|HEAD /receipts/{document_id}/pdf`, `POST /receipts/{document_id}/locate`, `POST /receipts/telemetry` — see [CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api) for the full signatures.

The viewer renders one page at a time and always keeps the "Check latest on AGC" escape hatch. This is the trust boundary: missing, mismatched, corrupt, ambiguous, or failed provenance never draws a highlight — an uncertain match shows nothing rather than a guess.

### Statutory reference graph

A deterministic index of cross-references inside Employment Act 1955 receipts, in three phases: **Phase 1** live now (audited alias `act-265-reprint-2023-6fec2f07`, Feb 2023), **Phase 2** compares two independently audited snapshots, **Phase 3** (optional) lets the Retrieval Agent follow one published reference when a question explicitly asks about it. Timeline dates label observed snapshots, not exact legal effective dates.

Flags: `REFERENCE_GRAPH_ENABLED` (base graph), `REFERENCE_GRAPH_COMPARISON_ENABLED` (snapshot comparison, needs the base flag too), `FOLLOW_REFERENCES_ENABLED` (binds the agent's `follow_references` tool, needs `AGENTIC_RETRIEVAL=1` too). All default off, all fail open. Full flag semantics, the follow operation's exact constraints (five-edge cap, one hop, deterministic ordering), and the audited-snapshot table are in [CONTRIBUTING.md](CONTRIBUTING.md#statutory-reference-graph-operator-workflow) and [CONTEXT.md](CONTEXT.md).

- `GET /reference-graph/status`, `GET /reference-graph/neighborhood`, `GET /reference-graph/snapshots`, `GET /reference-graph/compare` — flag-gated statutory cross-reference lookups; see [CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api) for the full query-parameter signatures.

The graph only identifies targets — it never supplies answer text or a citation itself. Same-Act text always comes from the anchor's own extraction; nothing here changes what gets cited.

### Eval dashboard API

The developer-only `/evals` page needs `NEXT_PUBLIC_EVALS=1` at build time. It uses a dedicated corpus (`EVALS_DATABASE_URL`) — never falls back to the app's `DATABASE_URL`.

- `GET /evals/sets` — the eval sets: `end_to_end` (default), `grounding` and `routing`. The other endpoints take `?set=`; see [CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api).
- `GET /evals/workflow` — data for the workflow map on `/evals` ([CONTRIBUTING.md](CONTRIBUTING.md#running-evals)).
- `GET /evals/cases` — every case with its saved result and status.
- `GET /evals/coverage` — static dataset counts, fixed coverage-gap flags, best-effort eval-corpus staleness check.
- `POST /evals/run { set, subset }` — stream one subset from an isolated subprocess; the accepted values are listed in [CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api). SSE events: `run_start`, `case_start`, `case_result`, `run_summary`, `error`, `done`.
- `POST /evals/cancel` — terminate the single active eval subprocess; returns `cancelled` or `no_active_run`.
- `GET /evals/results` — last saved report for the set, or 404 when no run is available.

`/evals/run`, `/evals/cancel`, `/evals/results` and `/evals/cases` need a sign-in token from a user in `EVALS_ADMIN_USER_IDS` ([CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api)).

The server refuses stale corpora, blocks concurrent runs, and kills a run when its browser stream disconnects — no abandoned page keeps burning tokens.

### Threads

`GET /threads` lists the signed-in user's saved threads, newest first. `GET /threads/{thread_id}` returns that thread's `messages`: each assistant message carries its `citations`, `commentary` and `currency_labels`, so receipts open after a reload. Only completed turns are saved. See ADR 0022. `DELETE /threads/{thread_id}` lets the owner delete a thread: [CONTRIBUTING.md](CONTRIBUTING.md#5-start-the-api).

### Memory

- **Conversation history** — server-side, keyed by `thread_id`, trimmed to a token budget (ADR 0008). The client never resends prior turns.
- **Semantic memory** (cross-thread, off by default) — remembers a practitioner's preferences and recurring topics across threads, as soft framing hints, never cited or treated as fact. Confidential client/matter facts excluded by construction. Flags and mechanics: [CONTRIBUTING.md](CONTRIBUTING.md#2-environment-variables). Full model: [CONTEXT.md](CONTEXT.md) and ADR 0010/0012.

## Docs & data

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — local setup, env vars & feature flags, running evals, model overrides
- **[Architecture map](CONTRIBUTING.md#architecture-map)** — which directory owns what, and when to read it
- **[Graph map](CONTRIBUTING.md#graph-map)** — every agent node and edge, and which node writes each state field
- **[CONTEXT.md](CONTEXT.md)** — domain language, supervisor rules, query-language behaviour, memory model
- **[docs/data-pipeline.md](docs/data-pipeline.md)** — the five scrape → embed steps and the JSON each produces
- **[docs/corpus-receipts.md](docs/corpus-receipts.md)** — immutable corpus lifecycle, storage, rollout, and rollback
- **[docs/deployment.md](docs/deployment.md)** — how production runs: services, dashboard settings, env vars by service
- **`docs/adr/`** — architecture decision records

### Eval harness

`evals/dataset.json` holds 79 hand-validated cases: Evidence Act 1950, Penal Code, PDPA 2010,
Companies Act 2016, Employment Act 1955, plus escalation cases that must be blocked. 40 of them are
Bahasa Malaysia or code-switched.

A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered) runs a 10-case smoke
eval against the GPT-4.1 defaults. It posts the judge pass rate and key L1 metrics as a PR comment,
and fails if the pass rate drops below 80%. The gated `/evals` dashboard adds static coverage
analysis, interactive subset runs, per-case drill-down, and a per-scenario summary. A second set, `grounding`, scores the grounding judge claim by claim against labelled verdicts.

Multi-part cases are scored by how many of their provisions the agent cited, not by one expected
section. `evals/retrieval_recall.py` scores retrieval on its own, so a retrieval regression is not
hidden behind answer quality. See [CONTRIBUTING.md](CONTRIBUTING.md) for dedicated eval-database
setup, multi-part and bilingual scoring, retrieval recall, and local usage.

`evals/reference_follow_dataset.json` is the separate Phase 3 enablement gate: asserts lookup-before-follow ordering, at most one follow call, positive/incoming selection, no invocation on ordinary exact/topical/broad/unrelated-Act queries. Fails fast unless both retrieval flags are explicitly on.

<details>
<summary><strong>Project structure</strong></summary>

```text
ai-legal-tool/
├── run.py              # CLI entrypoint (pipeline steps 1–5)
├── agent/              # LangGraph agent
│   ├── graph.py        # nodes, edges, retry loop, checkpointer + store wiring
│   ├── state.py        # AgentState, Message, Citation, QueryEvent/Result types
│   ├── query_lifecycle.py   # run_query / run_query_stream + barge-in cancellation (ADR 0014)
│   ├── query_policy.py      # history trimming, MAX_RETRIES
│   ├── llm_factory.py       # provider-agnostic LLM factory (Claude/Gemini/OpenAI)
│   ├── memory/         # Semantic Memory write + maintenance (ADR 0010/0012)
│   ├── retrieval/      # agentic retrieval: search, tools, ReAct agent (ADR 0013)
│   └── nodes/          # router, contextualize, retriever, recall, synthesiser,
│                       #   citation_validator, grounding_check, supervisor, conversational
├── api/
│   ├── main.py         # FastAPI app: query/resume/cancel + feature routers
│   ├── auth.py         # Supabase access-token check (current_user_id)
│   ├── threads.py      # GET /threads, GET and DELETE /threads/{id}
│   ├── threads_store.py # thread ownership and saved turns (psycopg2)
│   ├── receipts.py     # immutable PDF delivery + strict on-demand locator API
│   └── evals.py        # eval coverage, isolated subprocess SSE, cancellation, saved results
├── corpus/             # identities, manifest/audit, extraction, storage, DB lifecycle + CLI
├── citation_receipts/  # delivery/locator compatibility façade + telemetry
├── reference_graph/    # statutory cross-reference graph: build, audit, promote, load (CLI)
├── schemas/            # JSON schemas backing the reference-graph audit/promote steps
├── scraper/            # pipeline steps 1–4 (index, detail, PDFs, extract) + parsers
├── ingestion/          # step 5: embed + ingest into pgvector
├── evals/              # dataset, coverage logic, L1/L2 checks, runner, eval DB setup, debug tools
├── tests/              # unit tests (graph retry, checkpointer memory, ...)
├── frontend/            # Next.js app-router chat UI (Vercel AI SDK)
├── migrations/          # additive SQL: corpus provenance, reference graph, saved threads
├── data/                 # scraped corpus + deterministic manifest/coverage and pilot receipt assets
├── .github/workflows/   # evals.yml smoke run
└── docs/                # PRD, build-log, ADRs, data-pipeline reference
```

</details>
