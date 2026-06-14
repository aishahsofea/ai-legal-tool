"""
FastAPI backend for the Malaysian Legal Research AI Assistant.

Single endpoint: POST /query
- Accepts { query, thread_id } JSON (conversation memory lives server-side, keyed by thread_id)
- Streams Server-Sent Events (SSE) with progressive status updates and the final response
- Designed to be consumed by the Next.js frontend via Vercel AI SDK / EventSource

SSE event types:
  { "type": "status",   "message": "..." }          — progress update (router/retriever/synthesiser)
  { "type": "response", "content": "...",
    "citations": [...], "violations": [...] }        — final answer
  { "type": "error",    "message": "..." }           — unrecoverable error
  { "type": "done" }                                 — stream complete
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent.graph import lifespan_graph
from agent.query_lifecycle import run_query_stream, set_graph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with lifespan_graph() as g:
        set_graph(g)
        yield


app = FastAPI(title="Malaysian Legal Research API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to frontend URL in production
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str
    thread_id: str


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_STATUS_MESSAGES = {
    "router":          "Classifying query...",
    "retriever":       "Searching {n} sections across Malaysian Acts...",
    "synthesiser":     "Drafting response...",
    "supervisor":      "Checking policy compliance...",
    "increment_retry": "Refining response...",
    "escalate":        "Escalating to human lawyer...",
}


async def _stream_query(query: str, thread_id: str) -> AsyncGenerator[str, None]:
    try:
        async for event in run_query_stream(query, thread_id):
            yield _sse(event)
    except Exception as exc:
        logger.exception("Agent error for query: %s", query)
        yield _sse({"type": "error", "message": f"An error occurred: {str(exc)}"})
    yield _sse({"type": "done"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query")
async def query_endpoint(req: QueryRequest):
    return StreamingResponse(
        _stream_query(req.query, req.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
