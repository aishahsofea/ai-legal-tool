# CLAUDE.md

## Keeping docs in sync

When a change touches the agent graph (nodes/edges), the API contract (request/response shapes, endpoints, SSE events), env vars/config, or the top-level project structure, update the relevant living docs in the same change: `README.md`, `CONTRIBUTING.md`, `CONTEXT.md`.

Do NOT edit `docs/PRD.md`, `docs/agent-hardening-backlog.md`, `docs/adr/*`, or `docs/build-log.md` to reflect the new state — these are frozen decision records of what was true/decided at the time, not living docs.

## Doc voice

Living docs (`README.md`, `CONTRIBUTING.md`, `CONTEXT.md`, `docs/data-pipeline.md`, `docs/corpus-receipts.md`) must read as plain English — short sentences, no jargon-stacking, no nested clauses. Same text serves human readers and agents; don't write a "technical" version and a "readable" version. Concrete over abstract: name the file, the flag, the command, not "the relevant configuration."

That's the goal. These three checks are how you know you hit it — a rewrite that passes none of them is a reword, not a rewrite:

1. **One fact, one home.** Every flag, constraint, and number is stated in full in exactly one doc. Other docs state what it does in a sentence and link. `CONTRIBUTING.md` owns operator/dev detail (flags, commands, exact behavior). `CONTEXT.md` owns domain definitions. `README.md` owns highlights only — if a README paragraph restates a flag's full semantics, cut it to a sentence plus a link. This is where real length comes off.
2. **Count the words.** `wc -w` before and after. Restructuring prose usually moves the count a few percent; cutting duplication moves it 20%+. A rewrite that claims to simplify but barely moves the count didn't simplify anything.
3. **Diff for dropped facts.** Read the actual diff, not a summary of it. Removing a duplicate is the goal; removing the only copy of an endpoint, a safety invariant, or an env var is a regression. This has happened: a "verified" rewrite pass silently dropped `POST /receipts/telemetry` from the repo entirely.

Precision beats brevity when they conflict. Operational invariants ("amendment-only files are blockers, never base Acts", "never infer provenance", every fail-open rule) are load-bearing — an operator acts on them. Shorten the sentence around them; never cut the fact.

## Build Log

Short notes on challenges and learnings. Full entries in `docs/build-log.md`.
