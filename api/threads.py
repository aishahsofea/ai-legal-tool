"""Thread history for the signed-in user, plus owner-only delete (ADR 0022)."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from agent import query_lifecycle
from api import threads_store
from api.auth import current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/threads")


def _messages(turns: list[dict]) -> list[dict]:
    messages = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["query"]})
        messages.append({
            "role": "assistant",
            "content": turn["response"],
            "citations": turn["citations"] or [],
            "commentary": turn["commentary"] or [],
            "currency_labels": turn["currency_labels"] or [],
        })
    return messages


@router.get("")
async def list_threads(user_id: str = Depends(current_user_id)):
    return await asyncio.to_thread(threads_store.list_threads, user_id)


@router.get("/{thread_id}")
async def get_thread(thread_id: str, user_id: str = Depends(current_user_id)):
    thread = await asyncio.to_thread(threads_store.get_thread, thread_id, user_id)
    if thread is None:
        raise HTTPException(404, "Thread not found")
    turns = thread.pop("turns")
    return {**thread, "messages": _messages(turns)}


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request, user_id: str = Depends(current_user_id)):
    # Same 404 rule as main._require_owner; importing main here would be a cycle.
    if not await asyncio.to_thread(threads_store.owns, thread_id, user_id):
        raise HTTPException(404, "Thread not found")
    await request.app.state.agent_runtime.ensure_started()
    try:
        await query_lifecycle.delete_checkpoint(thread_id)
    except Exception:
        # Delete fails closed, unlike writes (ADR 0022): keep the row so a retry still passes the owner check.
        logger.exception("checkpoint delete failed for thread=%r", thread_id)
        raise HTTPException(500, "Could not delete thread")
    await asyncio.to_thread(threads_store.delete_thread, thread_id, user_id)
