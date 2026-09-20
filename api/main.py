"""
FastAPI backend for the Malaysian Legal Research AI Assistant.

Single endpoint: POST /query
- Accepts { query, thread_id, user_id? } JSON. Conversation memory lives server-side keyed
  by thread_id; user_id (optional) scopes cross-thread Semantic Memory per practitioner (ADR 0010).
- Streams Server-Sent Events (SSE) with progressive status updates and the final response
- Designed to be consumed by the Next.js frontend via Vercel AI SDK / EventSource

SSE event types:
  { "type": "status",    "message": "..." }          — progress update (router/retriever/synthesiser)
  { "type": "tool_call", "name": "...",
    "summary": "..." }                                — a retrieval tool fired (agentic retrieval)
  { "type": "node",      "name": "...", "model": "...",
    "duration_ms": 0 }                                — a node finished a model call; one per call,
                                                        in execution order (PROCESS panel)
  { "type": "response",  "content": "...", "citations": [...],
    "violations": [...], "commentary": [...] }        — final answer. "commentary"
                                                        (web publisher notes, ADR 0020) is
                                                        present only when the turn found at
                                                        least one — omitted, never `[]`,
                                                        the rest of the time
  { "type": "interrupt", "question": "...",
    "interrupt_id": "..." }                           — graph paused for clarification;
                                                        answer via POST /resume (ADR 0015)
  { "type": "error",     "message": "..." }           — unrecoverable error
  { "type": "done" }                                 — stream complete

Endpoints:
  POST /query        { query, thread_id, user_id? } — run a turn (SSE stream)
  POST /resume       { thread_id, value, user_id? }  — answer a clarify interrupt (SSE stream)
  POST /cancel       { thread_id }                   — barge-in: stop the in-flight turn
  GET|HEAD /receipts/{document_id}/pdf              — verified immutable bytes/redirect
  POST /receipts/{document_id}/locate               — locate one verified Evidence Span
  POST /receipts/telemetry                           — sanitized browser receipt failures
  GET  /reference-graph/status                       — graph availability (flag-gated)
  GET  /reference-graph/neighborhood                 — one-hop direct in/out edges (flag-gated)
  GET  /reference-graph/snapshots                    — promoted audited snapshot selector
  GET  /reference-graph/compare                      — one-hop snapshot comparison (separate flag)
  GET  /evals/coverage                              — static eval coverage + corpus status
  POST /evals/run    { subset }                     — run a subset (SSE stream)
  POST /evals/cancel                                — stop the active eval run
  GET  /evals/results                               — last persisted eval report
"""
import json
import logging
import os
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.evals import router as evals_router
from api.reference_graph import router as reference_graph_router
from api.receipts import router as receipts_router

load_dotenv()

from agent.query_lifecycle import cancel_thread, run_query_stream, set_graph

logger = logging.getLogger(__name__)


class _AgentRuntime:
    """Start chat resources only for chat requests, never for graph/health."""

    def __init__(self) -> None:
        self._context = None
        self._lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        if self._context is not None:
            return
        async with self._lock:
            if self._context is not None:
                return
            from agent.graph import lifespan_graph
            context = lifespan_graph()
            graph = await context.__aenter__()
            self._context = context
            set_graph(graph)

    async def close(self) -> None:
        if self._context is not None:
            context, self._context = self._context, None
            await context.__aexit__(None, None, None)


def _report_receipt_coverage() -> None:
    """Say on the first line how much of the registry this deployment can serve.

    A container ships the manifest but not most of the bytes it describes, so a
    deployment can look healthy and still answer 503 for everything that was
    never uploaded. One line at boot beats discovering that one request at a
    time. It must never stop the app from starting.
    """
    try:
        from citation_receipts.registry import get_receipt_registry
        from citation_receipts.service import delivery_mode
        from corpus.coverage import log_receipt_coverage

        log_receipt_coverage(
            get_receipt_registry(),
            delivery_mode=delivery_mode(),
            cdn_base_url=os.getenv("CORPUS_CDN_BASE_URL", "").strip(),
        )
    except Exception:
        logger.exception("receipt_coverage unavailable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = _AgentRuntime()
    app.state.agent_runtime = runtime
    _report_receipt_coverage()
    try:
        yield
    finally:
        await runtime.close()


app = FastAPI(title="Malaysian Legal Research API", lifespan=lifespan)
app.include_router(evals_router)
app.include_router(receipts_router)
app.include_router(reference_graph_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to frontend URL in production
    allow_methods=["POST", "GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Length", "Content-Range", "ETag", "Location"],
)


class QueryRequest(BaseModel):
    query: str
    thread_id: str
    # Weak, per-browser practitioner identity used to scope Semantic Memory across
    # threads (ADR 0010). Optional so older clients keep working; absent means the
    # memory path simply has no practitioner to attach durable facts to.
    user_id: str | None = None


class CancelRequest(BaseModel):
    thread_id: str


class ResumeRequest(BaseModel):
    thread_id: str
    # The user's answer to a clarify interrupt. Fed to the graph as Command(resume=value)
    # so the paused turn continues on the same thread_id (ADR 0015).
    value: str
    user_id: str | None = None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_STATUS_MESSAGES = {
    "router":          "Classifying query...",
    "contextualize":   "Resolving follow-up...",
    "retriever":       "Searching {n} sections across Malaysian Acts...",
    "synthesiser":     "Drafting response...",
    "supervisor":      "Checking policy compliance...",
    "increment_retry": "Refining response...",
    "escalate":        "Escalating to human lawyer...",
    "conversational":  "Responding...",
}


async def _stream_query(
    query: str | None,
    thread_id: str,
    user_id: str | None,
    *,
    resume: str | None = None,
) -> AsyncGenerator[str, None]:
    try:
        async for event in run_query_stream(query, thread_id, user_id, resume=resume):
            yield _sse(event)
    except Exception as exc:
        logger.exception("Agent error for query=%r resume=%r", query, resume)
        yield _sse({"type": "error", "message": f"An error occurred: {str(exc)}"})
    yield _sse({"type": "done"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query")
async def query_endpoint(req: QueryRequest, request: Request):
    await request.app.state.agent_runtime.ensure_started()
    return StreamingResponse(
        _stream_query(req.query, req.thread_id, req.user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/resume")
async def resume_endpoint(req: ResumeRequest, request: Request):
    """Resume a turn paused at a clarify interrupt (ADR 0015).

    The graph suspended at the clarify node and emitted an `interrupt` SSE event on the
    prior /query stream; this feeds the user's answer back as Command(resume=value) and
    streams the continuation (the resolved turn's real response) on the same thread_id.
    """
    await request.app.state.agent_runtime.ensure_started()
    return StreamingResponse(
        _stream_query(None, req.thread_id, req.user_id, resume=req.value),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.post("/cancel")
async def cancel_endpoint(req: CancelRequest):
    """Barge-in: stop the in-flight turn for a thread (the Stop button / Esc).

    Server-authoritative so Stop fires even if the client can't cleanly abort the SSE
    connection. Idempotent; returns no_active_run when nothing is running. See ADR 0014.
    """
    cancelled = cancel_thread(req.thread_id)
    return {"status": "cancelled" if cancelled else "no_active_run"}
