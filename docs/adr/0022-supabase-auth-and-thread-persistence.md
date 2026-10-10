# Sign-in with Supabase Auth, and threads stored in their own tables

Date: 2026-10-10

ADR 0010 keyed Semantic Memory on a `user_id` the browser made up and kept in `localStorage`. This ADR replaces that auth part only. The rest of ADR 0010 still stands: the three memory tiers, the `(user_id, "semantic")` namespace, background extraction.

Two gaps showed up in `#191`. A reload empties the sidebar, because threads live only in React state. And anyone can pass another person's `user_id` and read or write that person's memory.

## Decisions

- **Sign-in is GitHub OAuth through Supabase Auth.** The project already runs on Supabase (ADR 0021). GitHub OAuth needs no email delivery in production.
- **Signed-out users see a login wall.** There is no guest mode, because it would need a second code path that says "history is not saved". The wall is also simpler, and it limits who can spend the model budget.
- **The backend takes `user_id` from the verified access token.** The request body may still carry `user_id`. It is ignored, so old clients do not break.
- **Access tokens are verified against the project's JWKS first.** The legacy HS256 secret is used only if the Supabase project still signs tokens with HS256. Check which applies at the start of the auth work.
- **A thread belongs to one user.** A request on a `thread_id` the caller does not own returns 404, not 403, so ids of other people's threads are not confirmed to exist.
- **Threads are stored in two new tables, `threads` and `thread_turns`.** Each row keeps the query, the response, the citations, the commentary and the currency labels.
- **A turn is written only when it completes.** A turn paused for clarification, or cancelled, is not stored.
- **Old anonymous memory is not migrated.** Existing `localStorage` UUIDs and their Semantic Memory stay in the store, but no account can reach them. They are orphaned.

## Why not rebuild threads from the checkpoint

`#191` first proposed rebuilding messages and citations from the LangGraph checkpoint. That does not work:

- `history` in the checkpoint holds only `{role, content}`, with the disclaimer stripped (`agent/graph.py:150-153`). Citations are not in it.
- `_start_turn` resets `citations`, `commentary` and `currency_labels` at the start of every turn (`agent/graph.py:121-131`). The latest checkpoint holds only the last turn's citations.
- A rebuilt thread would lose the citations of every earlier turn. Receipts for those turns could not open.

The receipt data (`document_id` and evidence) sits inside `citation.receipt`. Stored citations are enough to open a receipt with no new query.

## Considered options

- **Rebuild from the checkpoint.** Rejected, for the reasons above.
- **Magic link.** Rejected. It needs working email delivery in production.
- **Guest mode.** Rejected. See the login wall decision.
- **Migrate old anonymous memory into accounts.** Rejected for now. There is no way to prove which account owns a given UUID.

## Consequences

- **API contract changes.** `/query`, `/resume` and `/cancel` need `Authorization: Bearer <token>`. A missing, malformed, expired or wrong-audience token returns 401. `GET /threads` lists the caller's threads. `GET /threads/{id}` fetches one.
- **Writing a turn fails open.** If saving a completed turn to the database fails, the error is logged and the answer is still delivered. A database fault must not break a research turn.
- **Memory continuity breaks once.** Existing users start with empty Semantic Memory after sign-in.
- **Open sign-up can spend the model budget.** The cheap fix is to turn off sign-ups in Supabase and create the judge accounts by hand.
- **The sync eval path keeps working.** `run_query` takes `user_id` directly and does not go through the API.
- **`/receipts/*` and `/reference-graph/*` stay public.** The browser fetches them directly. Locking them down is separate work.

## Related

- ADR 0010 — the memory tiers and the weak `user_id` this replaces.
- ADR 0012 — practitioner background stored in Semantic Memory.
- ADR 0021 — the paid Supabase project this auth runs on.
