"""The chat checkpointer and store must survive a dead or cancelled connection (#262)."""
import asyncio
import os
import unittest
import uuid
from contextlib import AsyncExitStack, ExitStack, closing
from unittest.mock import patch

import psycopg2
from psycopg_pool import AsyncConnectionPool

from agent import query_lifecycle
from agent.graph import lifespan_graph
from tests._graph_helpers import patch_async_happy_path

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


async def _answer(state):
    return {"draft_response": "Section 5 of Example Act applies. This does not constitute legal advice.", "citations": []}


def _terminate_other_backends() -> None:
    with closing(psycopg2.connect(TEST_DATABASE_URL)) as admin, admin.cursor() as cursor:
        admin.autocommit = True
        cursor.execute(
            "select pg_terminate_backend(pid) from pg_stat_activity "
            "where datname = current_database() and pid <> pg_backend_pid()"
        )


@unittest.skipUnless(TEST_DATABASE_URL, "needs TEST_DATABASE_URL pointing at a disposable Postgres")
class PooledCheckpointerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._saved_graph = query_lifecycle.graph
        stack = ExitStack()
        # tests/conftest.py forces CHECKPOINTER=memory; undo it so lifespan_graph opens Postgres.
        stack.enter_context(patch.dict(os.environ, {"DATABASE_URL": TEST_DATABASE_URL}))
        os.environ.pop("CHECKPOINTER", None)
        patch_async_happy_path(stack, _answer)
        stack.enter_context(patch("agent.query_lifecycle.threads_store.append_turn"))
        stack.enter_context(patch("agent.query_lifecycle.schedule_extraction"))
        stack.enter_context(patch("agent.query_lifecycle.schedule_pruning"))
        self.addCleanup(stack.close)

        self.lifespan = AsyncExitStack()
        self.graph = await self.lifespan.enter_async_context(lifespan_graph())
        query_lifecycle.set_graph(self.graph)

    async def asyncTearDown(self):
        await self.lifespan.aclose()
        query_lifecycle.graph = self._saved_graph
        query_lifecycle._active_runs.clear()

    async def _assert_fresh_turn_answers(self):
        events = [e async for e in query_lifecycle.run_query_stream("a question", f"pool-{uuid.uuid4().hex}")]
        self.assertIn("response", [e.get("type") for e in events])

    async def _assert_store_round_trips(self):
        namespace = ("pool-test", uuid.uuid4().hex)
        await self.graph.store.aput(namespace, "k", {"v": 1}, index=False)
        item = await self.graph.store.aget(namespace, "k")
        self.assertEqual(item.value, {"v": 1})

    async def _cancel_midcommand(self):
        pool = self.graph.checkpointer.conn

        async def sleeper():
            async with pool.connection() as conn:
                await conn.execute("select pg_sleep(2)")

        task = asyncio.create_task(sleeper())
        await asyncio.sleep(0.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    def test_checkpointer_and_store_share_a_pool(self):
        self.assertIsInstance(self.graph.checkpointer.conn, AsyncConnectionPool)
        self.assertIs(self.graph.store.conn, self.graph.checkpointer.conn)

    async def test_saver_recovers_after_connections_are_terminated(self):
        await self._assert_fresh_turn_answers()
        await asyncio.to_thread(_terminate_other_backends)
        await self._assert_fresh_turn_answers()

    async def test_store_recovers_after_connections_are_terminated(self):
        await self._assert_store_round_trips()
        await asyncio.to_thread(_terminate_other_backends)
        await self._assert_store_round_trips()

    async def test_saver_recovers_after_cancel_midcommand(self):
        self.assertIsInstance(self.graph.checkpointer.conn, AsyncConnectionPool)
        await self._cancel_midcommand()
        for _ in range(3):
            await self._assert_fresh_turn_answers()

    async def test_store_recovers_after_cancel_midcommand(self):
        self.assertIsInstance(self.graph.store.conn, AsyncConnectionPool)
        await self._cancel_midcommand()
        for _ in range(3):
            await self._assert_store_round_trips()


if __name__ == "__main__":
    unittest.main()
