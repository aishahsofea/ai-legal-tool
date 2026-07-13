# Barge-in: cancel an in-flight turn the way Esc stops Claude

Date: 2026-07-12

A practitioner who changes their mind mid-answer — the draft is streaming and they realise they asked the wrong thing — had no way to stop it. The turn ran to completion, burned tokens, and the only recourse was to wait it out and ask again. This ADR adds **barge-in**: a user-initiated stop that aborts the running turn immediately and lets the next prompt start clean, the same interaction as pressing Esc in an agent CLI.

This is deliberately **not** LangGraph's `interrupt()` primitive. `interrupt()` is *graph-initiated* — a node decides to pause for human input. Barge-in is *user-initiated* cancellation of a run that no node chose to pause. The two are different mechanisms and can coexist; only cancellation is in scope here.

## Decisions

- **Barge-in is cancellation, surfaced as `POST /cancel { thread_id }`.** SSE is server→client only, so the client cannot signal "stop" over the `/query` connection. Cancellation is therefore either the client aborting the `fetch` (client-disconnect) or an explicit `POST /cancel` on a second connection. `/cancel` is server-authoritative: a Stop fires even if the browser can't cleanly abort the stream, and it works cross-tab. It returns `{"status": "cancelled" | "no_active_run"}` and is idempotent.
- **One active run per `thread_id`, held as an `asyncio.Task` in `query_lifecycle._active_runs`.** The graph is driven inside an inner producer task whose events are bridged to the SSE generator over an `asyncio.Queue`. Holding the task handle is what lets a *different* request (`/cancel`) or a *new turn* on the same thread cancel the in-flight run. A new `POST /query` on a thread first cancels and unwinds any run still in flight for it — so "change my mind, ask something else" needs no explicit cancel, and two turns can never race on the same checkpoint.
- **Cancellation must abort the live model request, not wait it out.** With every LLM node running sync-in-a-threadpool, a cancel could only ever take effect at the *next node boundary* — a Stop during drafting would wait out the whole draft (threads can't be cancelled). So the five LLM nodes (`router`, `contextualize`, `synthesiser`, `conversational`, `grounding_check`) gained **async twins**: `RunnableCallable(sync, async)`, exactly the pattern the `recall` node already used. `astream` awaits the async twin, so `asyncio.CancelledError` propagates into the awaited `ainvoke` and tears down the in-flight HTTP request. The sync twin is retained because the eval path (`run_query` → `graph.invoke`) needs synchronous execution.
- **Pure-Python nodes keep no twin.** `supervisor` and `citation_validator` make no LLM call (rule-based / deterministic), and `start_turn` / `record_turn` / `escalate` are trivial. They run to completion in microseconds; async twins would be noise. `retriever` is left sync for now — node-boundary cancellation there is acceptable, and its async conversion (the ReAct agent path especially) is larger; deferred.
- **An abandoned turn writes nothing.** The response yield and all side effects (LangSmith feedback, Semantic Memory extraction/pruning) live *after* the `astream` loop in `_drive_query_stream`, so a mid-loop `CancelledError` skips them by construction. `record_turn` never runs, so the aborted turn leaves no `history` entry — verified by test, including that a fresh prompt on the same thread records only itself and the cancelled turn's pending checkpoint task neither resumes nor duplicates.

## Considered options

- **Client-disconnect only, no `/cancel` endpoint.** Rejected as the sole mechanism. Aborting the `fetch` does flow through the same cancellation path, but relying on it alone means a Stop is only as reliable as the browser's disconnect propagation and can't be triggered from another connection. `/cancel` is ~15 lines and makes Stop deterministic; client-disconnect remains supported as the implicit path.
- **Cooperative cancel flag checked between nodes (no async twins).** Rejected as insufficient for the stated goal. It stops at node boundaries but cannot abort an in-flight `invoke` running in a thread — a Stop during the synthesiser draft (the longest call) would still wait out the full generation. That is exactly the case barge-in exists to fix.
- **Convert every node to async, including the retriever.** Deferred, not rejected. The five LLM twins cover the calls a user is realistically waiting on; the retriever's conversion is a larger change for a node that is rarely the long pole. It can adopt the same twin pattern later without touching this design.
- **A guard that clears `snapshot.next` before starting a new turn.** Rejected as unnecessary. The concern was that a cancelled run leaves a pending checkpoint task that a fresh input might resume. Testing showed a fresh `{"query": …}` input **supersedes** the pending task cleanly (`start_turn` re-enters from the top and its per-turn reset overwrites the stale partial state), so no explicit guard is needed.
- **LangGraph `interrupt()`.** Out of scope — it is graph-initiated pause, not user-initiated cancellation. Left for a future human-in-the-loop change (clarification / approval), which would reuse the same `thread_id` continuation this establishes.

## Consequences

- **New API surface: `POST /cancel { thread_id }`.** Documented in `README.md`; the frontend gets a Stop button (abort the `fetch`, optionally call `/cancel`, clear the UI optimistically) and treats "new prompt on same thread" as an implicit barge-in.
- **The LLM nodes are now sync+async twins.** Each affected node file exposes `x_node` and `ax_node` sharing extracted prompt-building / post-processing helpers; `graph.py` registers them via `RunnableCallable`. The fail-open `except Exception` blocks are unaffected — `CancelledError` subclasses `BaseException`, so a barge-in propagates cleanly rather than being swallowed as a node failure.
- **Perceived responsiveness depends on the frontend halting optimistically.** The server aborts the in-flight async call promptly, but the snappiest feel comes from the client stopping its own UI the instant Stop is pressed rather than waiting for the stream to close. That lives in the frontend repo (integration note), not here.
- **Living docs updated.** `README.md`, `CONTRIBUTING.md`, and `CONTEXT.md` describe the endpoint and the cancellation semantics.

## Related

- ADR 0003 — Python/LangGraph runtime and the checkpointer that makes same-`thread_id` continuation (and thus clean post-cancel restarts) possible.
- ADR 0010 — the memory write path that a cancelled turn must *not* trigger; the post-loop placement of those side effects is what guarantees it.
- ADR 0007 — `start_turn`'s per-turn reset (raw query never overwritten) is what lets a superseding prompt start clean over a cancelled turn's partial state.
