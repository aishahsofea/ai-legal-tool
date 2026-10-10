"""Read-only thread history for the signed-in user (ADR 0022)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from api import threads_store
from api.auth import current_user_id

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
