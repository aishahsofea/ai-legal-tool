# PRD: Malaysian Legal Research AI Assistant — v1

**Target pilot date:** mid-June 2026
**Status:** needs-triage

---

## Problem Statement

Malaysian law practitioners — including junior associates, paralegals, and law students — spend significant time manually searching through legislation to answer research queries. The authoritative source (lom.agc.gov.my) is a raw document portal with no semantic search, no cross-Act querying, and no ability to ask natural-language questions. Practitioners must know exactly which Act and section to look for before they can find it — the tool offers no help for topical or comparative queries.

Additionally, practitioners code-switch between Bahasa Malaysia and English in everyday work, but existing tools are language-siloed.

## Solution

A multi-turn AI research assistant that lets Malaysian law practitioners ask natural-language questions — in English, BM, or mixed — and receive cited, statute-grounded answers. The agent retrieves relevant sections from a local corpus of Malaysian Acts, synthesises a response with section-level citations, and enforces a strict policy layer that prevents legal advice and escalates ambiguous queries to a human lawyer.

The system is built on a LangGraph agent graph with four nodes (router, retriever, synthesiser, supervisor) backed by a pgvector corpus of section-level chunks extracted from AGC portal PDFs.

---

## User Stories

**Research queries**

1. As a law practitioner, I want to ask a natural-language question about a specific Act section, so that I can get the section text without manually navigating the AGC portal.
2. As a law practitioner, I want to ask a topical question ("which Acts govern data privacy for employers?"), so that I can discover relevant legislation I may not have known about.
3. As a law practitioner, I want to ask for all penalty provisions within a specific Act, so that I can draft advice without reading the entire Act.
4. As a law practitioner, I want to write my query in Bahasa Malaysia, English, or a mix of both, so that I can work in my natural register without switching modes.
5. As a law practitioner, I want every answer to cite the specific section and Act it draws from, so that I can verify the source and use it in a court document.
6. As a law practitioner, I want citations to link directly to the relevant page of the official AGC PDF, so that I can verify the exact wording without searching.
7. As a law practitioner, I want the agent to respond in the same language register I used (BM or English), so that the interaction feels natural.

**Policy and safety**

1. As a law practitioner, I want the agent to decline requests for advice on my specific legal situation, so that I am not misled into treating the tool as a substitute for a qualified lawyer.
2. As a law practitioner, I want the agent to escalate my query to a human lawyer when the query involves a specific client situation, so that I get appropriate professional help.
3. As a law practitioner, I want every response to include a disclaimer that it is not legal advice, so that I understand the tool's limitations.
4. As a law practitioner, I want the agent to only make claims that are supported by a specific statute citation, so that I can trust the factual accuracy of responses.

**Multi-turn conversation**

1. As a law practitioner, I want to ask follow-up questions in the same session without repeating context, so that I can refine my research iteratively.
2. As a law practitioner, I want the agent to remember which Acts and sections we discussed earlier in the conversation, so that follow-up questions are coherent.

**Frontend**

1. As a law practitioner, I want to see responses stream in progressively, so that I do not wait for a 10-second blank screen before seeing any output.
2. As a law practitioner, I want citations rendered as tappable links within the response, so that I can jump directly to the source.
3. As a law practitioner, I want a persistent disclaimer banner visible at all times, so that I am never in doubt about the tool's scope.

---

## Implementation Decisions

### Modules

**1. PDF Downloader** (`scraper/step3_pdfs.py`)

- Iterates over `data/acts_metadata/*.json`
- Selection priority: `latest_reprint_pdf` → `latest_amendment_pdf` → skip
- URL-encodes all paths before fetching (99% of AGC URLs contain literal spaces)
- Writes to `data/pdfs/en/{act_number}.pdf`; resumable (skips existing files)
- Emits `data/pdfs/download_report.json` with counts and failure list
- Timeout: 120s per file; reuses existing session and retry logic

**2. Text Extractor + Chunker** (`ingestion/extractor.py`)

- Uses pymupdf to extract text from each PDF
- Detects scanned PDFs by average character count per page (< ~100 chars/page → flag `is_scanned`, skip)
- Identifies section boundaries by regex on Malaysian Act numbering conventions (e.g. `^(\d+[A-Z]?)\.\s`)
- Each chunk contains: `act_number`, `act_title`, `section_number`, `content`, `page_number`, `language`
- `page_number` enables `{pdf_url}#page={n}` deep links in the frontend
- Writes `data/chunks/en/{act_number}.json`

**3. Embedder + Ingestor** (`ingestion/ingestor.py`)

- Embeds each chunk with OpenAI `text-embedding-3-small` (1536 dimensions)
- Inserts into pgvector (Supabase) with all metadata columns
- Schema: `id`, `act_number`, `act_title`, `section_number`, `language`, `content`, `page_number`, `embedding vector(1536)`
- Resumable: skips chunks already present by `(act_number, section_number, language)` unique key

**4. LangGraph Agent** (`agent/graph.py`)

- Four nodes:
  - **router** — classifies query as `statute_lookup` / `topical_search` / `provision_extraction` / `escalate`; triggers immediate `escalate` response for queries containing "my client", "I have been charged", "am I liable"
  - **retriever** — calls the appropriate retrieval tool; searches both `en` chunks (all queries); no pre-filtering by language (practitioners code-switch)
  - **synthesiser** — drafts a response grounded in retrieved chunks; outputs structured JSON with `answer` (prose) and `citations` array (`act_title`, `act_number`, `section_number`, `pdf_url`, `page_number`)
  - **supervisor** — checks draft against 4 policy rules before output; blocks or rewrites on violation; routes to human hand-off if unresolvable

- Supervisor rules enforced:
  1. Response must not contain "you should", "you must", "in your case", "I recommend"
  2. Every legal claim must cite "Section X of Act Y"
  3. Response must include a disclaimer that it is not a substitute for professional legal advice
  4. Queries with "my client", "I have been charged", "am I liable" → human hand-off before retrieval

**5. FastAPI Backend** (`api/main.py`)

- Single `/stream` endpoint accepting `{ query, history }` POST
- Streams LangGraph output as Server-Sent Events (SSE)
- Deployed on Railway

**6. Eval Harness** (`evals/`)

- Dataset: `evals/dataset.json` — ~50–80 manually validated test cases
  - Generated semi-automatically: pymupdf extracts section text → Claude generates 1–2 natural language questions per section → human accepts/rejects
  - Covers: statute lookup, topical search, provision extraction, policy violation cases (queries that should be blocked)
- LLM-as-judge: secondary Claude call scoring each response on:
  - **Citation accuracy** — did the agent cite the correct section?
  - **Policy compliance** — did the supervisor correctly allow/block the response?
- GitHub Actions CI: runs eval suite on every push to `main`; posts pass rate to PR; failing score blocks merge
- Headline metrics: citation accuracy + policy compliance rate (before/after for write-up)

**7. Next.js Frontend** (`frontend/`)
scoring each response on:

- **Citation accuracy** — did the agent cite the correct section?
- **Policy compliance** — did the supervisor correctly allow/block the response?
- GitHub Actions CI: runs eval suite on every push to `main`; posts pass rate to PR; failing score blocks merge
- Headline metrics: citation accuracy + policy compliance rate (before/after for write-up)

**7. Next.js Frontend** (`frontend/`)

- Single-page chat UI
- `useChat` hook (Vercel AI SDK) consuming SSE from FastAPI `/stream`
- Citations rendered as `<a href="{pdf_url}#page={n}">Section X, Act Y</a>` links
- Persistent disclaimer banner: "This tool is for legal research only and does not constitute legal advice."
- No auth for pilot (URL-based access); no history persistence for v1

### Infrastructure

- **Frontend:** Vercel (Next.js)
- **Backend:** Railway (FastAPI + LangGraph)
- **Database:** Supabase (Postgres + pgvector, free tier)
- **Tracing:** LangSmith — automatic via `LANGCHAIN_TRACING_V2=true`; public trace links for portfolio
- **Embeddings:** OpenAI `text-embedding-3-small`
- **Generation:** Anthropic Claude API (claude-sonnet-4-6 or later)

### Bilingual strategy

- v1 pilot corpus: English only. BM queries accepted and handled via cross-lingual embedding similarity.
- BM corpus added before public write-up. Retrieval accuracy improvement on BM queries measured as before/after eval.
- Cited text is always English (authoritative court version); response prose mirrors dominant language of the query.

---

## Testing Decisions

**What makes a good test here:** tests should verify external behaviour (does the agent return a correctly cited response for this query? does the supervisor block this policy-violating query?) not implementation details (which retrieval function was called, how many chunks were fetched).

**Modules to test:**

- **Extractor + Chunker** — unit tests: given a known PDF fixture, does the chunker produce chunks with correct `section_number` and `page_number`? Does it correctly flag a scanned PDF?
- **Supervisor node** — unit tests: given a draft response containing "you should...", does the supervisor block it? Given a query with "am I liable", does it trigger escalation before retrieval?
- **Eval harness (end-to-end)** — integration tests using the full `evals/dataset.json`: citation accuracy ≥ target threshold, policy compliance rate ≥ target threshold. These run in CI.

**Not tested in isolation:** the router classification (too tightly coupled to LLM behaviour; covered by end-to-end evals instead).

---

## Out of Scope

- **Case law (court judgments)** — deferred to v2. Free source (CommonLII) has robots.txt restrictions on AI crawlers and incomplete coverage. See ADR-0001.
- **BM corpus in v1 pilot** — English corpus only for June 2026. BM added before public write-up.
- **Scanned PDFs** — detected and skipped during Phase 3. Predominantly pre-1990 ordinances. Documented as a known gap.
- **Authentication / user accounts** — URL-based access for pilot. Auth added if pilot scales.
- **Chat history persistence** — responses are stateless between sessions in v1.
- **MCP server** — tools will be wrapped as an MCP server post-v1 before public write-up.
- **Subsidiary legislation (P.U. documents)** — metadata is scraped but PDFs are not ingested in v1. Added in a later phase.
- **Repealed Acts** — excluded from the corpus by default; available in the index for historical research.

---

## Further Notes

- The primary portfolio artefact is the public LangSmith trace dashboard, not the UI. Hiring managers evaluating agent engineering skill will inspect traces.
- The write-up is planned as a 3-post series: (1) data pipeline, (2) agent architecture and supervisor pattern, (3) eval-driven development. Published on personal blog + Medium; cross-posted to LinkedIn.
- Pilot users: 2–3 law students at UM/UiTM as the entry point. Their real queries seed the eval dataset, replacing semi-auto generated cases over time.
- Railway free tier sleeps after inactivity — acceptable for pilot, needs keep-alive or upgrade before public launch.
- The `page_number`-based deep link (`{pdf_url}#page={n}`) should be validated against an actual AGC PDF URL in the browser before the frontend is built around it.
