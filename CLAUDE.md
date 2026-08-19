# CLAUDE.md

## Keeping docs in sync

When a change touches the agent graph (nodes/edges), the API contract (request/response shapes, endpoints, SSE events), env vars/config, or the top-level project structure, update the relevant living docs in the same change: `README.md`, `CONTRIBUTING.md`, `CONTEXT.md`.

Do NOT edit `docs/PRD.md`, `docs/agent-hardening-backlog.md`, `docs/adr/*`, or `docs/build-log.md` to reflect the new state — these are frozen decision records of what was true/decided at the time, not living docs.

## Doc voice

Living docs (`README.md`, `CONTRIBUTING.md`, `CONTEXT.md`) must read as plain English — short sentences, no jargon-stacking, no nested clauses. Same text serves human readers and agents; don't write a "technical" version and a "readable" version. Concrete over abstract: name the file, the flag, the command, not "the relevant configuration."

## Build Log

Short notes on challenges and learnings. Full entries in `docs/build-log.md`.
