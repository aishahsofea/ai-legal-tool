"""
FastAPI backend for the Malaysian Legal Research AI Assistant.

Single endpoint: POST /query
- Accepts { query, history } JSON
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
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

from agent.graph import graph
from agent.state import AgentState

logger = logging.getLogger(__name__)

app = FastAPI(title="Malaysian Legal Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to frontend URL in production
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    query: str
    history: list[dict] = []   # reserved for multi-turn (v2)


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


async def _stream_query(query: str) -> AsyncGenerator[str, None]:
    initial_state: AgentState = {
        "query":            query,
        "query_type":       "",
        "retrieved_chunks": [],
        "draft_response":   "",
        "citations":        [],
        "violations":       [],
        "final_response":   "",
        "retry_count":      0,
    }

    accumulated: dict = {}

    try:
        async for chunk in graph.astream(initial_state):
            node_name = next(iter(chunk))
            state_update: dict = chunk[node_name]
            accumulated.update(state_update)

            # Send a status event for every node except the final output nodes
            if node_name == "retriever":
                n = len(state_update.get("retrieved_chunks", []))
                msg = f"Found {n} relevant sections. Drafting response..."
            elif node_name in _STATUS_MESSAGES:
                msg = _STATUS_MESSAGES[node_name]
            else:
                msg = f"Processing ({node_name})..."

            yield _sse({"type": "status", "message": msg})

            # If this node set final_response and violations are empty, we're done
            if state_update.get("final_response") and not accumulated.get("violations"):
                break

        final   = accumulated.get("final_response", "")
        citations = accumulated.get("citations", [])
        violations = accumulated.get("violations", [])

        if not final:
            yield _sse({"type": "error", "message": "No response generated."})
        else:
            yield _sse({
                "type":       "response",
                "content":    final,
                "citations":  citations,
                "violations": violations,
            })

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
        _stream_query(req.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
