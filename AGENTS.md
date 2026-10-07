# AGENTS.md

Read and follow `.agent/standards/AGENTS.md` before editing code. Rules in this repository's `AGENTS.md` take precedence when they conflict.

> Canonical project instructions live in [CLAUDE.md](CLAUDE.md). Read and follow that file before making changes in this repository.

## Long or paid runs

Before any command that runs longer than a few minutes or spends money on a model API (a smoke run, a full eval, a re-extraction), tell the user the rough time and the rough cost. Give both numbers and their source, for example the `Usage (estimated)` block that `python -m evals.run_evals` prints. Say when one is a guess.

State this before the command starts, not after. If the user gave a spending cap, say whether the run fits under it. Running several in parallel counts as one job: give the total.

## Keeping docs in sync

When a change touches the agent graph (nodes/edges), the API contract (request/response shapes, endpoints, SSE events), env vars/config, or the top-level project structure, update the relevant living docs in the same change: `README.md`, `CONTRIBUTING.md`, `CONTEXT.md`.

Do NOT edit `docs/PRD.md`, `docs/agent-hardening-backlog.md`, `docs/adr/*`, or `docs/build-log.md` to reflect the new state — these are frozen decision records of what was true/decided at the time, not living docs. "Frozen" means the decision and its rationale never change to match later reality. It does not mean the prose is exempt from the "Doc voice" section of [CLAUDE.md](CLAUDE.md). You can rewrite an ADR for readability as long as the decision, the reasoning, and every fact stay exactly as recorded at the time.

## Build Log

Short notes on challenges and learnings. Full entries in `docs/build-log.md`.
