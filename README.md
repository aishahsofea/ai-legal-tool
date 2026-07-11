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
│                    │  provision_extraction / conversational / escalate
└──────┬─────────────┘
       │ (escalate short-circuits here; conversational short-circuits
       │  via recall, then the conversational node)
       ▼
┌────────────────────┐
│  contextualize     │  rewrites an elliptical follow-up into a
│                    │  self-contained standalone query for retrieval
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  retriever         │  pgvector similarity search over section-level
│                    │  chunks (EN + BM). With AGENTIC_RETRIEVAL on, a
│                    │  ReAct agent picks search_statutes / lookup_section
│                    │  tools and can re-search; fails open to this path.
└──────┬─────────────┘
       │
       ▼
┌────────────────────┐
│  recall            │  pulls the practitioner's saved preferences into
│                    │  the answer as framing hints — also runs before the
│                    │  conversational node (off by default —
│                    │  SEMANTIC_MEMORY_RECALL)
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

Three short-circuits aren't pictured above: a query the `router` classifies as `escalate` skips straight to `record_turn` with a fixed human hand-off message (the `escalate` node); an unambiguously non-legal message (greeting, name, thanks, "what can you do?") the `router` classifies as `conversational` passes through `recall` (so saved preferences can personalise the reply) and then answers with a short, warm reply (the `conversational` node — no retrieval, no supervisor, no citation or disclaimer) before `record_turn`; and a `supervisor` violation with a retry remaining (`MAX_RETRIES`) loops back before re-running citation/grounding checks. The router leans legal on ties — `conversational` is reserved for messages with no legal substance.

**Retry routing by violation kind.** The single retry (`MAX_RETRIES=1`) is split by what went wrong. A *policy/phrasing* violation (advice phrase, missing disclaimer) loops back to `synthesiser` via `increment_retry` to re-draft against the same chunks. An *evidence* violation (a citation that isn't in the retrieved sources, or a grounding check flagging an unsupported claim) instead routes — only when `AGENTIC_RETRIEVAL` is on — to `retry_retrieve`, which re-runs the retrieval agent with feedback about the gap and then re-enters `retriever → recall → synthesiser`. `citation_validator` and `grounding_check` tag their evidence-shaped findings into a separate `evidence_violations` list that drives this choice. An evidence gap that survives the re-retrieval still fails closed to the safe fallback.

**Agentic retrieval (`AGENTIC_RETRIEVAL`, off by default).** When on, the `retriever` node is a LangGraph `create_react_agent` that binds two tools — `search_statutes` (semantic search) and `lookup_section` (exact section lookup) — and decides which to call, with what arguments, and whether to re-search on weak hits. Its tools stream `tool_call` SSE events (surfaced in the frontend PROCESS panel) and write found chunks into the agent's state; the node fails open to the deterministic pgvector path on any error or empty result, so turning the flag on can never retrieve less than the proven path. See ADR 0013.

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
│   ├── graph.py                    # graph: nodes, edges, retry loop, checkpointer + store wiring
│   ├── state.py                    # AgentState, Message, Citation, QueryEvent/Result types
│   ├── query_lifecycle.py          # run_query / run_query_stream (thread_id-based)
│   ├── query_policy.py             # MAX_HISTORY_TOKENS, MAX_RETRIES, token-budget history trimming
│   ├── llm_factory.py              # provider-agnostic LLM factory (Claude/Gemini/OpenAI)
│   ├── memory/                     # Semantic Memory write path (ADR 0010)
│   │   ├── schemas.py              # PractitionerProfile, RecurringTopic (extraction schemas)
│   │   └── extractor.py            # background extract → upsert via LangMem/Trustcall
│   ├── retrieval/                  # agentic retrieval (ADR 0013, AGENTIC_RETRIEVAL)
│   │   ├── search.py               # pgvector semantic_search + exact_section_lookup
│   │   ├── tools.py                # search_statutes / lookup_section @tools
│   │   └── agent.py                # create_react_agent + RetrievalState
│   └── nodes/
│       ├── router.py
│       ├── conversational.py
│       ├── contextualize.py
│       ├── retriever.py            # deterministic path + agentic wrapper (fail-open)
│       ├── recall.py               # Semantic Memory read path (reads what extractor writes)
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
data: {"type": "status",    "message": "Classifying query..."}
data: {"type": "tool_call", "name": "search_statutes", "summary": "Searching statutes: “…”"}
data: {"type": "status",    "message": "Searching Malaysian Acts..."}
data: {"type": "status",    "message": "Drafting response..."}
data: {"type": "status",    "message": "Checking policy compliance..."}
data: {"type": "response",  "content": "...", "citations": [...], "violations": []}
data: {"type": "done"}
```

The `tool_call` event (`name`, `summary`) is emitted only on the agentic-retrieval path (`AGENTIC_RETRIEVAL` on), once per retrieval tool the agent calls; the frontend renders these as steps in the collapsible PROCESS panel.

On a follow-up turn where the contextualize node rewrites the query into a standalone form, a `"Resolving follow-up..."` status is emitted before retrieval (the rewritten text itself is never surfaced). If the supervisor finds a violation and a retry remains, a `"Refining response..."` status is emitted and `synthesiser → citation_validator → grounding_check → supervisor` re-runs once (bounded by `MAX_RETRIES`). If the router classifies the query as `escalate`, an `"Escalating to human lawyer..."` status is emitted and the response is a fixed hand-off message. If the router classifies an unambiguously non-legal message as `conversational`, a `"Responding..."` status is emitted and the response is a short, warm reply with empty `citations` and no disclaimer.

Citation objects include `act_number`, `act_title`, `section_number`, `pdf_url` (with `#page=N` anchor), and `page_number`.

### Conversation memory

Every request carries a `thread_id`; the client never resends prior turns. History is kept server-side in a LangGraph checkpointer, keyed by `thread_id`:

- `DATABASE_URL` set (default) → `PostgresSaver` / `AsyncPostgresSaver`, persisted in the same Postgres instance as pgvector
- `CHECKPOINTER=memory` or no `DATABASE_URL` → in-process `MemorySaver` (local dev/tests)

History accumulates across turns and is trimmed to a token budget (`MAX_HISTORY_TOKENS`, default 4000, env-overridable) when read by the router, contextualize, and synthesiser nodes. Trimming drops whole turns (user+assistant pairs) oldest-first until the remainder fits — so a slice never begins on a dangling assistant reply — with a hard floor that keeps the most recent turn even if it alone exceeds the budget. Token size is a proxy via a single local `tiktoken` encoder shared across providers; the budget bounds prompt cost/distraction, not the context window. See ADR 0008 and `evals/history_budget.py` for tuning. Assistant turns are stored **disclaimer-free** — the legal-advice disclaimer is stripped at record-time so later nodes don't re-read repeated boilerplate (the disclaimer still reaches the user in the response).

### Semantic memory (cross-thread, dark by default)

**Semantic Memory** remembers the practitioner across all of them — their durable preferences and the topics they keep returning to, scoped by `user_id`. It lives in a cross-thread store that runs on the same backends as the checkpointer: Postgres when `DATABASE_URL` is set, in-memory otherwise. See ADR 0010 and `CONTEXT.md` for the model.

The `recall` node reads those facts and passes them to the answering node — the synthesiser on the legal path, or the conversational node on the small-talk short-circuit — as hints about how to frame a reply. The practitioner's own **profile** (background, language, format style) is fetched deterministically by kind and always surfaced when present, rather than made to win a vector search against the current query (ADR 0012); recurring **topics** are retrieved by similarity to the query. They are soft context, not legal substance: never cited, never treated as fact, and never written back into the conversation history. The retrieved statutes and the query always win when they conflict. Both legal and conversational turns feed the background **write** path (ADR 0012), because a practitioner's own background often surfaces in small talk ("I'm a software engineer exploring legal tech") and is a durable fact worth remembering — distinct from confidential client/matter facts, which are excluded by construction.

Facts get *into* the store on the **write path** (`agent/memory/extractor.py`): after a legal or conversational turn is delivered, a background job extracts durable practitioner facts — the practitioner's own profile (`PractitionerProfile`: background, preferences) and recurring research topics (`RecurringTopic`) — via LangMem (Trustcall underneath, dedup/merge-aware) and upserts them into the same `(user_id, "semantic")` namespace. It runs **off the hot path** — fired only after the response event, so it can never delay or alter the turn — and stores **only** the practitioner's own identity, preferences, and topics: confidential client or matter facts and sensitive personal life are excluded by construction (schema field descriptions + the extraction prompt).

The write path only inserts, so the topic collection grows and can accumulate near-duplicates and multiple profiles. The **maintenance path** (`agent/memory/pruner.py`) keeps the namespace bounded and high-quality: it collapses duplicate profiles into one, consolidates near-duplicate topics (clustered via the store's own vector search), and evicts low-value topics beyond a generous cap by an **importance + recency** score — retrieval frequency (recorded by `recall` in a side `(user_id, "semantic_meta")` namespace) weighted against each item's write time. It is **not** TTL: a stale-but-frequently-recalled fact outlives recent chatter. Like extraction it runs off the hot path (fired after the response, size-debounced), is fail-open, and is deliberately conservative — it never deletes the sole profile and never empties a namespace. Tune the cap, similarity threshold, and weights with `evals/semantic_memory.py`.

Each path has its own flag, all **off by default** and fail-open: `SEMANTIC_MEMORY_RECALL` (read), `SEMANTIC_MEMORY_EXTRACT` (write), and `SEMANTIC_MEMORY_PRUNE` (maintenance). With a flag off, no `user_id` (or the `anonymous` sentinel), an empty store, or any error, the turn is identical to one produced without the feature.

---

## Eval Harness

`evals/dataset.json` contains hand-validated test cases for the Evidence Act 1950, Penal Code, PDPA 2010, Companies Act 2016, Employment Act 1955, and escalation cases that should be blocked.

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run evals locally. A GitHub Actions workflow (`.github/workflows/evals.yml`, manually triggered) runs a 15-case smoke eval against the GPT-4.1 defaults and posts the judge pass rate and key L1 metrics as a PR comment; it fails if the judge pass rate drops below 80%.
