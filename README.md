# Malaysian Legal Research AI Assistant

> Ask about Malaysian legislation in English, Bahasa Malaysia, or a mix of both — and get an answer grounded in the actual statute text, with citations that deep-link to the exact page of the official PDF.

A LangGraph agent over a pgvector corpus of section-level chunks scraped from the
[AGC portal](https://lom.agc.gov.my). It **cites every legal claim, never gives legal
advice, and hands off to a human lawyer** when a query is about a specific client situation.

**Stack:** LangGraph · FastAPI (Railway) · Next.js (Vercel) · Postgres + pgvector (Supabase) · OpenAI `text-embedding-3-small` · GPT-4.1 — provider-agnostic via `agent/llm_factory.py` (Claude/Gemini swappable; Claude runs the eval judge).

## Highlights

- **Cited, statute-grounded answers.** Every response links act + section + PDF page. A citation validator and a grounding check reject claims the retrieved text doesn't actually support.
- **Bilingual.** English / Bahasa Malaysia / code-switched queries, retrieving across EN and BM chunks at once.
- **Guardrails, not vibes.** A supervisor blocks legal-advice phrasing, requires a disclaimer, and escalates client-specific questions to a human before retrieval even starts.
- **Agentic retrieval (optional).** A ReAct agent chooses between semantic search and exact-section lookup and re-searches on weak hits — failing open to a deterministic pgvector path, so it can never retrieve *less* than the proven path.
- **Memory.** Server-side per-thread history, plus optional cross-thread *semantic memory* that remembers a practitioner's preferences and recurring topics.
- **Evaluated.** A hand-validated benchmark with deterministic (L1) assertions and an LLM judge (L2), gated in CI.

## Quick start

Full setup — env vars, database, frontend, evals — lives in [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

```bash
pip3 install -r requirements.txt
python run.py --step all                     # build the knowledge base (~1h, one-time, resumable)
uvicorn api.main:app --port 8000 --reload    # start the API
```

Then `cd frontend && npm install && npm run dev` for the chat UI at `localhost:3000`.

## How it works

A query carries a `thread_id` and flows through a LangGraph graph: it's classified, retrieved
against, drafted, then checked for citations, grounding, and policy before it ever reaches the user.

```text
query + thread_id (EN / BM / mixed)
  → start_turn           load thread history, reset per-turn scratch state
  → router               classify (or short-circuit: escalate → hand-off, conversational → warm reply)
  → contextualize        rewrite an elliptical follow-up into a standalone query
  → retriever            pgvector similarity search over section chunks (or an agentic ReAct agent)
  → recall               surface saved practitioner preferences as framing hints (optional)
  → synthesiser          draft the answer with citations (act, section, page deep-link)
  → citation_validator   reject citations absent from the retrieved sources
  → grounding_check      flag claims the retrieved text doesn't support
  → supervisor           enforce policy — retries once on a violation
  → record_turn          append the turn to checkpointed history
```

<details>
<summary><strong>Short-circuits &amp; retry routing</strong></summary>

Three paths skip the full pipeline:

- **escalate** — a client-specific query ("am I liable…", "my client…") jumps straight to `record_turn` with a fixed human hand-off message.
- **conversational** — an unambiguously non-legal message (greeting, name, thanks, "what can you do?") passes through `recall` then answers with a short, warm reply — no retrieval, no supervisor, no citations, no disclaimer.
- **retry** — a `supervisor` violation with a retry remaining (`MAX_RETRIES=1`) loops back before re-running the checks.

The single retry is split by *what went wrong*. A **policy/phrasing** violation (advice phrase, missing disclaimer) loops back to `synthesiser` to re-draft against the same chunks. An **evidence** violation (a citation not in the sources, or an unsupported claim) instead routes — only when `AGENTIC_RETRIEVAL` is on — to `retry_retrieve`, which re-runs the retrieval agent with feedback about the gap. An evidence gap that survives re-retrieval fails closed to the safe fallback.

</details>

See [CONTEXT.md](CONTEXT.md) for the domain model and supervisor rules, and `docs/adr/` for the design decisions behind these (ADR 0008 history budget · 0010/0012 semantic memory · 0013 agentic retrieval).

## API

```bash
uvicorn api.main:app --port 8000 --reload
```

Health check: `GET /health`. The query endpoint streams Server-Sent Events:

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does Section 17 of the Evidence Act say about admissions?", "thread_id": "demo-1"}'
```

```text
data: {"type": "status",    "message": "Classifying query..."}
data: {"type": "tool_call", "name": "search_statutes", "summary": "Searching statutes: “…”"}
data: {"type": "status",    "message": "Searching Malaysian Acts..."}
data: {"type": "status",    "message": "Drafting response..."}
data: {"type": "status",    "message": "Checking policy compliance..."}
data: {"type": "response",  "content": "...", "citations": [...], "violations": []}
data: {"type": "done"}
```

- **`response`** carries `content`, `violations`, and `citations` — each with `act_number`, `act_title`, `section_number`, `pdf_url` (with `#page=N` anchor), and `page_number`.
- **`tool_call`** (`name`, `summary`) is emitted only on the agentic-retrieval path, once per retrieval tool the agent calls; the frontend renders these in the collapsible PROCESS panel.
- **`status`** messages track the phase and reflect short-circuits: `"Resolving follow-up..."`, `"Refining response..."` (a retry), `"Escalating to human lawyer..."`, or `"Responding..."` (conversational).

**Barge-in (stop a running turn):** `POST /cancel { thread_id }` cancels the in-flight turn for a thread — the Stop button / Esc. Cancellation aborts the live model request and the `/query` SSE stream for that thread ends on its own. A cancelled turn writes nothing — no `response`, no history, no memory — so the next prompt starts clean. Returns `{"status": "cancelled"}` or `{"status": "no_active_run"}`; idempotent. There is one active run per `thread_id`, so a new `POST /query` on the same thread also supersedes any in-flight run — "change my mind, ask something else" needs no explicit cancel. See ADR 0014.

### Memory

- **Conversation history** is kept server-side in a LangGraph checkpointer keyed by `thread_id` — the client never resends prior turns. `DATABASE_URL` set → `PostgresSaver`; otherwise an in-process `MemorySaver`. History is trimmed to a token budget (`MAX_HISTORY_TOKENS`, default 4000) in whole turns, oldest first (ADR 0008).
- **Semantic memory** (cross-thread, **off by default**) remembers a practitioner across threads — their durable preferences and recurring topics, scoped by `user_id`. A background write path extracts them, `recall` reads them back as soft framing hints (never cited, never treated as fact), and a maintenance path keeps the namespace bounded. Confidential client/matter facts are excluded by construction. Each path has its own fail-open flag (`SEMANTIC_MEMORY_RECALL` / `_EXTRACT` / `_PRUNE`). See [CONTEXT.md](CONTEXT.md) and ADR 0010/0012.

## Docs & data

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — local setup, env vars & feature flags, running evals, model overrides
- **[CONTEXT.md](CONTEXT.md)** — domain language, supervisor rules, query-language behaviour, memory model
- **[docs/data-pipeline.md](docs/data-pipeline.md)** — the five scrape → embed steps and the JSON each produces
- **`docs/adr/`** — architecture decision records

### Eval harness

`evals/dataset.json` holds hand-validated cases for the Evidence Act 1950, Penal Code, PDPA 2010,
Companies Act 2016, Employment Act 1955, plus escalation cases that must be blocked. A GitHub Actions
workflow (`.github/workflows/evals.yml`, manually triggered) runs a 15-case smoke eval against the
GPT-4.1 defaults and posts the judge pass rate and key L1 metrics as a PR comment — failing if the
pass rate drops below 80%. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run evals locally.

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
├── api/main.py         # FastAPI SSE: POST /query { query, thread_id }, POST /cancel { thread_id }
├── scraper/            # pipeline steps 1–4 (index, detail, PDFs, extract) + parsers
├── ingestion/          # step 5: embed + ingest into pgvector
├── evals/              # dataset, L1 assertions, L2 Claude judge, runner, debug tools
├── tests/              # unit tests (graph retry, checkpointer memory, ...)
├── frontend/           # Next.js app-router chat UI (Vercel AI SDK)
├── data/               # scraped index, metadata, PDFs, chunks, HTTP cache
├── .github/workflows/  # evals.yml smoke run
└── docs/               # PRD, build-log, ADRs, data-pipeline reference
```

</details>
