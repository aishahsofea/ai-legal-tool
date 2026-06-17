# Implementation Plan: LangGraph Checkpointer (Server-Side Conversation Memory)

> **Handoff doc.** This is written for an implementing agent picking up cold. It assumes no
> prior conversation context. Read it top to bottom before writing code.

## 1. Goal

Replace the current "frontend resends full history on every request" mechanism with
**server-side conversation memory** backed by a LangGraph checkpointer.

After this change:
- The graph persists its state per conversation, keyed by a `thread_id`.
- The frontend sends `{ query, thread_id }` instead of `{ query, history }`.
- Conversations survive process restarts and are shared across workers (via Postgres backend).
- We get resumability / human-in-the-loop hooks "for free" later.

**Non-goals (do NOT do these here):** history-aware retrieval (separate task), token-budget
trimming, summarization. Keep the existing turn-count trimming.

## 2. Background: how memory works today

- Server is **stateless**. `graph.invoke(state)` runs and discards state.
- Frontend holds all conversation state in React (`frontend/lib/useResearchThreads.ts`) and
  rebuilds the `history` array on each submit (`useResearchThreads.ts:113`), sending it in the
  request body.
- `api/main.py` receives `{ query, history }`, passes to `run_query_stream`.
- `agent/query_lifecycle.py` trims history to the last `MAX_HISTORY_TURNS` (6) and builds a fresh
  `AgentState` (`_initial_state`) each call.
- `agent/graph.py` runs an ephemeral `AgentState` — **no checkpointer configured**.
- Only `router_node` and `synthesiser_node` read `history`. The retriever does not (out of scope here).

## 3. What a checkpointer is (one paragraph)

A checkpointer saves the graph's `AgentState` to a store after every node, tagged with a
`thread_id`. On the next `invoke`/`astream` call with the same `thread_id`, LangGraph **loads the
saved state first**, then merges the new input on top. The `thread_id` is passed via a config dict:
`config = {"configurable": {"thread_id": "..."}}`. We already have a per-conversation id on the
frontend (`thread.id` in `useResearchThreads.ts:111`) — reuse it as `thread_id`.

## 4. The critical mental-model shift

Because state now **persists across turns**, fields that are meant to be per-query
(`retry_count`, `violations`, `retrieved_chunks`, `draft_response`, `citations`, `final_response`,
`query_type`) will **leak from turn N into turn N+1** unless explicitly reset at the start of each
turn. Only `history` should accumulate. This drives the two new nodes in Phase 2.

---

## 5. Implementation phases

Do these in order. Each phase is independently testable. **Phase 1–3 use `MemorySaver` (in-process,
no new deps) so the logic can be verified before introducing Postgres in Phase 4.**

### Phase 1 — State schema: make `history` accumulate

File: `agent/state.py`

Add a reducer to the `history` field so node returns of `{"history": [...]}` concatenate instead
of overwrite. All other fields keep default overwrite semantics.

```python
from operator import add
from typing import Annotated, Literal, TypedDict

class AgentState(TypedDict):
    query: str
    history: Annotated[list[Message], add]   # accumulate across turns
    query_type: str
    response_language: str
    retrieved_chunks: list[dict]
    draft_response: str
    citations: list[Citation]
    violations: list[str]
    final_response: str
    retry_count: int
```

No behavior change yet (nothing returns `history`). Existing tests must still pass.

### Phase 2 — Graph: add `start_turn` (reset) and `record_turn` (append) nodes

File: `agent/graph.py`

**2a. Change `build_graph` to accept an optional checkpointer:**

```python
def build_graph(checkpointer=None) -> StateGraph:
    ...
    return g.compile(checkpointer=checkpointer)
```

Keep the module-level `graph = build_graph()` for now (Phase 4 wires the real checkpointer in).

**2b. Add two nodes:**

```python
def _start_turn(state: AgentState) -> dict:
    # Reset per-query fields so turn N does not inherit turn N-1's leftovers.
    # history is intentionally NOT reset (it accumulates via the reducer).
    return {
        "query_type": "",
        "response_language": "en",
        "retrieved_chunks": [],
        "draft_response": "",
        "citations": [],
        "violations": [],
        "final_response": "",
        "retry_count": 0,
    }

def _record_turn(state: AgentState) -> dict:
    # Append at the END so that DURING the turn, state["history"] holds prior turns only
    # (prevents the current query appearing twice in prompts).
    return {"history": [
        {"role": "user", "content": state["query"]},
        {"role": "assistant", "content": state.get("final_response", "")},
    ]}
```

**2c. Rewire entry/exit.** `start_turn` becomes the entry point; every path that previously went to
`END` now routes through `record_turn` first.

```python
g.add_node("start_turn", _start_turn)
g.add_node("record_turn", _record_turn)

g.set_entry_point("start_turn")
g.add_edge("start_turn", "router")

# router still escalates or proceeds, but END targets become record_turn
g.add_conditional_edges("router", _route_from_router, {
    END: "escalate",          # _route_from_router returns END for escalate; keep mapping
    "retriever": "retriever",
})
g.add_edge("escalate", "record_turn")        # was: END
g.add_edge("retriever", "synthesiser")
g.add_edge("synthesiser", "citation_validator")
g.add_edge("citation_validator", "grounding_check")
g.add_edge("grounding_check", "supervisor")
g.add_conditional_edges("supervisor", _route_from_supervisor, {
    "increment_retry": "increment_retry",
    END: "record_turn",       # was: END
})
g.add_edge("increment_retry", "synthesiser")
g.add_edge("record_turn", END)
```

> Note: `_route_from_router` returns the literal `END` to mean "escalate" (see existing mapping
> `{END: "escalate"}`). Leave that helper as-is; only the edge *targets* change.

### Phase 3 — Query lifecycle & API: thread through `thread_id`

File: `agent/query_lifecycle.py`

- Input on each turn becomes just `{"query": query}` — the `start_turn` node fills the rest.
- Build the config from `thread_id` and pass it to `astream` / `invoke`.
- Keep `trim_history`; it moves to **read-time** inside the nodes (Phase 3b).

```python
def _turn_input(query: str) -> dict:
    return {"query": query}

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}

def run_query(query: str, thread_id: str) -> QueryResult:
    state = graph.invoke(_turn_input(query), _config(thread_id))
    state = _fail_closed_if_violations(state)
    return { ... }   # unchanged shape

async def run_query_stream(query: str, thread_id: str) -> AsyncIterator[QueryEvent]:
    config = _config(thread_id)
    state: dict = {}
    async for update in graph.astream(_turn_input(query), config, stream_mode="updates"):
        node_name = next(iter(update.keys()), "")
        if node_name in _STATUS_MESSAGES:
            yield {"type": "status", "message": _STATUS_MESSAGES[node_name]}
        state.update(next(iter(update.values()), {}))
    state = _fail_closed_if_violations(state)
    ...  # rest unchanged
```

> `_initial_state` is no longer used for invocation. You may delete it or keep it for tests — but
> note tests will need updating (Phase 5).

**3b.** Move trimming into the nodes that read history:

- `agent/nodes/router.py:57` — `history = trim_history(state.get("history", []))`
- `agent/nodes/synthesiser.py:75` — same

Import `trim_history` from `agent.query_lifecycle`, OR (cleaner, avoids a circular-import risk)
move `trim_history` into `agent/query_policy.py` and import from there in all three places.
**Recommendation: move it to `query_policy.py`.**

File: `api/main.py`

```python
class QueryRequest(BaseModel):
    query: str
    thread_id: str

@app.post("/query")
async def query_endpoint(req: QueryRequest):
    return StreamingResponse(
        _stream_query(req.query, req.thread_id),
        ...
    )
```

Update `_stream_query(query, thread_id)` and its call to `run_query_stream(query, thread_id)`.

### Phase 4 — Swap MemorySaver → PostgresSaver (durability)

Once Phases 1–3 pass with `MemorySaver`, switch the backing store. Reuse the existing
`DATABASE_URL` (same Postgres instance as pgvector).

**4a. Dependency** — add to `requirements.txt`:

```
langgraph-checkpoint-postgres>=2.0
```

> This package uses **psycopg (v3)**, which is independent of the existing `psycopg2-binary`.
> Both can coexist. Do not replace psycopg2.

**4b. Wire it in** `agent/graph.py` (replace the module-level `graph = build_graph()`):

```python
import os
from langgraph.checkpoint.memory import MemorySaver

def _make_checkpointer():
    db_url = os.getenv("DATABASE_URL")
    if not db_url or os.getenv("CHECKPOINTER", "").lower() == "memory":
        return MemorySaver()
    from langgraph.checkpoint.postgres import PostgresSaver
    cp = PostgresSaver.from_conn_string(db_url)
    cp.setup()   # idempotent; creates checkpoint tables if absent
    return cp

graph = build_graph(_make_checkpointer())
```

> `PostgresSaver.from_conn_string` returns a context manager in some versions. Verify the installed
> version's API (`help(PostgresSaver.from_conn_string)`); if it is a context manager, open it at app
> startup and keep it alive for the process lifetime (e.g. enter it in a module-level
> `contextlib.ExitStack`, or use FastAPI lifespan). Pick whichever the installed version requires —
> do not assume.

**4c.** Run once against the deployed Neon/Postgres DB to create checkpoint tables (the `cp.setup()`
call handles this on first boot, but confirm tables exist: `checkpoints`, `checkpoint_writes`,
`checkpoint_blobs`).

### Phase 5 — Frontend

File: `frontend/lib/useResearchThreads.ts`

- Stop building/sending `history` (`useResearchThreads.ts:113`). Send `thread.id` as `thread_id`.
- `submitQuery` no longer needs to map prior messages into `QueryMessage[]`.

File: `frontend/lib/useQuery.ts` and `frontend/lib/queryTransport.ts`

- Change `submit(query, history)` → `submit(query, threadId)`.
- Update the request body to `{ query, thread_id }`.

> The frontend still keeps its own message list for *rendering* — that does not change. We are only
> removing `history` from the **network payload**, because the server now owns conversation memory.

### Phase 6 — Tests

Existing tests that build full `AgentState` dicts and invoke the graph will break because the entry
point and reset semantics changed.

- `tests/test_graph_retry.py` — `_initial_state()` no longer needs all fields; invoke now needs a
  config: `app.invoke({"query": "..."}, {"configurable": {"thread_id": "t1"}})`. The mocked nodes
  patch `agent.graph.*` — also patch/allow the new `start_turn`/`record_turn` (they are plain
  functions, no mocking needed, but assertions on `retry_count`/`violations` should still hold).
- `tests/test_query_lifecycle_fail_closed.py` — update `run_query`/`run_query_stream` calls to pass
  a `thread_id`.

**New tests to add:**

1. **Per-turn reset** — invoke twice on the same `thread_id` where turn 1 ends with `retry_count=1`;
   assert turn 2 starts fresh (retry loop works again, `retry_count` resets to 0 at `start_turn`).
2. **History accumulation** — invoke twice on the same `thread_id`; assert turn 2's state `history`
   contains turn 1's user+assistant messages, and that the nodes received prior history (not the
   current query duplicated).
3. **Thread isolation** — two different `thread_id`s do not see each other's history.

Run: `python -m pytest tests/ -q` (or `python -m unittest discover -s tests`).

---

## 6. Gotchas (do not skip)

1. **`retry_count` leak.** Without `start_turn`, turn 2 inherits `retry_count=1`; since
   `MAX_RETRIES=1`, the supervisor retry loop is dead on every turn after the first. This is the
   whole reason `start_turn` exists.
2. **Duplicate current query.** Record the turn at the END (`record_turn`). During the turn,
   `state["history"]` must contain prior turns only, or prompts show the query twice.
3. **Unbounded history.** The checkpoint stores ALL turns forever (good for durability). Always
   `trim_history()` before sending to an LLM, or token cost grows every turn.
4. **MemorySaver is not durable.** It is an in-process dict — fine for dev/tests, useless for the
   deployed pilot. Phase 4 (Postgres) is required for the actual persistence win.
5. **psycopg version.** `langgraph-checkpoint-postgres` uses psycopg3; keep psycopg2 for the
   retriever. They coexist.
6. **`response_language` default.** `start_turn` resets it to `"en"`; the router overwrites it
   immediately, so the default only matters on the escalate path. Confirm escalate responses are
   English (they are today).

## 7. Acceptance criteria

- [ ] A multi-turn conversation on one `thread_id` retains context server-side; the frontend sends
      no `history` in the request body (verify in browser Network tab — payload is `{ query, thread_id }`).
- [ ] Turn 2+ on the same thread resets `retry_count`/`violations`/`retrieved_chunks` etc.
      (per-turn-reset test passes).
- [ ] `history` accumulates across turns and is visible in the checkpoint.
- [ ] Two different `thread_id`s are isolated.
- [ ] With `PostgresSaver`, a conversation survives an API process restart.
- [ ] All existing tests pass after updates; 3 new tests added and passing.
- [ ] Escalation path still records the turn and returns the escalation response.

## 8. Rollback

The change is gated by the `CHECKPOINTER` env var and `DATABASE_URL` presence (Phase 4b). To roll
back to stateless behavior, the cleanest path is the git revert of this feature branch. There is no
partial-runtime toggle back to the `history`-in-payload contract once the frontend ships Phase 5 —
so land backend (Phases 1–4) and frontend (Phase 5) together, or feature-flag the frontend payload.

## 9. Suggested branch / commit breakdown

1. `feat(state): history reducer + start_turn/record_turn nodes` (Phases 1–2, MemorySaver)
2. `feat(api): thread_id-based invocation; read-time trimming` (Phase 3)
3. `feat(memory): PostgresSaver backend behind DATABASE_URL` (Phase 4)
4. `feat(frontend): send thread_id instead of history` (Phase 5)
5. `test(memory): per-turn reset, accumulation, thread isolation` (Phase 6)

Land 1–3 + 5 together (see Rollback). Keep 4 swappable via env var.
