"""Thread ownership and completed turns, stored apart from the LangGraph checkpoint (ADR 0022)."""

from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

import psycopg2
import psycopg2.extras

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "0002_threads.sql"


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _json(value):
    return None if value is None else psycopg2.extras.Json(value)


def apply_migration(connection) -> None:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(MIGRATION_PATH.read_text(encoding="utf-8"))


def claim_thread(thread_id: str, user_id: str, title: str | None) -> bool:
    """Create the thread for this user, or return False if another user already owns it."""
    with closing(_connect()) as connection, connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO threads (id, user_id, title) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (thread_id, user_id, title),
        )
        cursor.execute("SELECT user_id FROM threads WHERE id = %s", (thread_id,))
        return cursor.fetchone()[0] == user_id


def owns(thread_id: str, user_id: str) -> bool:
    with closing(_connect()) as connection, connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM threads WHERE id = %s AND user_id = %s", (thread_id, user_id))
        return cursor.fetchone() is not None


def append_turn(
    thread_id: str,
    query: str,
    response: str,
    citations: list,
    commentary: list | None = None,
    currency_labels: list | None = None,
) -> int:
    """Store a completed turn at the next index and return that index."""
    with closing(_connect()) as connection, connection, connection.cursor() as cursor:
        # The row lock serialises concurrent appends, so indexes stay contiguous.
        cursor.execute("UPDATE threads SET updated_at = NOW() WHERE id = %s RETURNING id", (thread_id,))
        if cursor.fetchone() is None:
            raise LookupError(f"thread {thread_id} not found")
        cursor.execute(
            """
            INSERT INTO thread_turns
                (thread_id, turn_index, query, response, citations, commentary, currency_labels)
            SELECT %s, COALESCE(MAX(turn_index) + 1, 0), %s, %s, %s, %s, %s
            FROM thread_turns WHERE thread_id = %s
            RETURNING turn_index
            """,
            (
                thread_id, query, response,
                _json(citations), _json(commentary), _json(currency_labels),
                thread_id,
            ),
        )
        return cursor.fetchone()[0]


def list_threads(user_id: str) -> list[dict]:
    with closing(_connect()) as connection, connection, connection.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    ) as cursor:
        cursor.execute(
            """
            SELECT id, title, created_at, updated_at FROM threads
            WHERE user_id = %s ORDER BY updated_at DESC
            """,
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_thread(thread_id: str, user_id: str) -> dict | None:
    """Return the thread with its turns in order, or None when this user does not own it."""
    with closing(_connect()) as connection, connection, connection.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    ) as cursor:
        cursor.execute(
            "SELECT id, title, created_at, updated_at FROM threads WHERE id = %s AND user_id = %s",
            (thread_id, user_id),
        )
        thread = cursor.fetchone()
        if thread is None:
            return None
        cursor.execute(
            """
            SELECT turn_index, query, response, citations, commentary, currency_labels, created_at
            FROM thread_turns WHERE thread_id = %s ORDER BY turn_index
            """,
            (thread_id,),
        )
        return {**thread, "turns": [dict(row) for row in cursor.fetchall()]}
