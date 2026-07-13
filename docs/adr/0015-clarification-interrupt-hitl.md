# Clarification: pause the graph to ask the practitioner a question

Date: 2026-07-13

Some queries cannot be researched as written — most often a section number with no Act named ("what does section 5 say?"). Until now the graph would push such a query through retrieval anyway and return a weak or wrong answer. This ADR adds **clarification**: when the router judges a query un-actionable, the graph *pauses*, asks the practitioner one question, and resumes with their answer folded in.

This is LangGraph's `interrupt()` primitive — a **graph-initiated pause**, the companion that ADR 0014 (barge-in) explicitly deferred. It is the mirror image of barge-in: barge-in is *user-initiated cancellation* of a run no node chose to pause; clarification is a *node choosing to pause* for human input. The two reuse the same single-active-run / same-`thread_id` continuation but never share a code path.

## Decisions

- **Clarification is a dedicated `clarify` node reached by a new router branch.** The router's existing structured-output call gains a `"clarify"` `query_type` and a `clarifying_question` field, so detection costs **zero extra latency** on the normal path. `_route_from_router` routes to `clarify` only when the query is `clarify` **and** a non-empty question was produced **and** the turn has not already asked one — an empty question or a second ambiguity falls through to the normal legal path rather than pausing on nothing or looping.
- **The clarify node is side-effect-free before its `interrupt()`.** LangGraph re-runs an interrupted node from the top on resume, so anything non-idempotent before the pause would fire twice. The node does nothing but call `interrupt({"type": "clarification", "question": …})` and, on resume, build its result from the returned answer.
- **On resume the node MERGES the original query with the answer into one self-contained query (option C), rather than letting the bare answer overwrite it.** The original intent ("section 5") lives only in `state["query"]`; the answer ("the Contracts Act 1950") lives only in the resume value; the interrupt exchange is not in `history`. Retrieval reads `query` / `standalone_query` — not the exchange — so overwriting `query` with the answer would make the turn retrieve on "the Contracts Act 1950" alone and **lose the section-5 intent**. Merging preserves both and matches the standalone-query philosophy `contextualize` already embodies (ADR 0007). String-merge to start; a one-call LLM merge is the drop-in upgrade path.
- **After the node, the merged query is re-classified by re-entering the router.** The edge is `clarify → router`, not `clarify → contextualize`: the clarified query needs a real `query_type` (it was `"clarify"`). A `clarified` flag set by the node makes the router branch fall through on the second pass, so a turn pauses **at most once** — no infinite clarify loop.
- **The interrupt surfaces over SSE and resumes over a new endpoint.** `_drive_query_stream` detects the `__interrupt__` update, emits `{"type": "interrupt", "question", "interrupt_id"}`, and **returns before the post-loop side effects** (LangSmith feedback, Semantic Memory extraction/pruning) — so a *paused* turn writes nothing, exactly like a *barged-in* one. `POST /resume { thread_id, value }` feeds `Command(resume=value)` back through the same producer-task / `_active_runs` machinery and streams the continuation (the resolved turn's real response).
- **A paused turn writes nothing until it completes.** `record_turn` runs only after resume, so an abandoned clarification (the practitioner asks something else instead of answering) leaves no `history` entry — a fresh `POST /query` on the thread supersedes the pending interrupt checkpoint, the same clean-restart property barge-in verified.
- **The clarify node keeps no async twin.** `interrupt()` is not an awaited model call, so there is nothing for a barge-in to tear down; the node runs to completion in microseconds. (Contrast the five LLM nodes, which need async twins per ADR 0014.) The sync eval path (`run_query` → `graph.invoke`) cannot resume an interrupt, so it fails safe: an `__interrupt__` in the result returns a `clarify` result carrying the question rather than crashing on the missing `final_response`.

## Considered options

- **Overwrite `query` with the raw answer (option A).** Rejected — it loses the original intent and retrieves on the answer alone. **Store the original + the clarification as two history entries (option B).** Rejected as insufficient on its own: `history` does not feed the *current* turn's retrieval, so B fixes future follow-ups but not the turn being clarified — and still needs a merge. Option C (merge into one self-contained query) is accurate for both the current turn and later follow-ups, at lower token cost than B.
- **Detect ambiguity in a new dedicated node before the router.** Rejected — it adds an LLM call to *every* query. Folding detection into the router's existing structured output is free.
- **Route `clarify → contextualize` directly.** Rejected — the merged query still carries `query_type="clarify"` and downstream needs a real type; re-entering the router is the honest re-classification.
- **A `while`/conditional loop to re-ask until unambiguous.** Rejected — the docs warn against looping `interrupt()` with non-deterministic logic. A single `clarified`-guarded pass is simpler and bounded; a still-ambiguous answer just proceeds to a best-effort retrieval.
- **Reuse `POST /query` with an optional `resume` field.** Rejected in favour of a dedicated `POST /resume`, mirroring `POST /cancel` from ADR 0014 — the two verbs stay legible and the request shapes don't overload.

## Consequences

- **New API surface: `POST /resume { thread_id, value, user_id? }`** and a new `interrupt` SSE event type. Documented in `README.md`; the frontend renders the question and puts the composer into an "answer the clarification" state, visually distinct from the barge-in Stop state.
- **New state fields** `clarifying_question` and `clarified`, reset per turn in `start_turn`; `query_type` gains `"clarify"`; `QueryEvent` gains the `interrupt` type with `question` / `interrupt_id`.
- **`run_query_stream` / `_drive_query_stream` accept a `resume` value** and drive `Command(resume=…)` when present; interrupt detection stays live on the resume pass (a resume can hit another interrupt).
- **Living docs updated** — `README.md`, `CONTRIBUTING.md`, `CONTEXT.md` describe the endpoint, the SSE event, and the graph-initiated-pause vs. user-initiated-cancel distinction.

## Related

- ADR 0014 — barge-in cancellation; establishes the single-active-run / `_active_runs` machinery and the same-`thread_id` clean-restart property this reuses, and is the mechanism this is explicitly *not* (pause vs. cancel).
- ADR 0007 — `contextualize`'s standalone-query philosophy that the merge follows, and `start_turn`'s per-turn reset that lets a superseding prompt discard an abandoned pause.
- ADR 0003 — the checkpointer that makes suspend-and-resume on a `thread_id` possible at all.
- ADR 0009 — the conversational short-circuit; clarify is a fourth router branch alongside escalate/conversational/legal.
