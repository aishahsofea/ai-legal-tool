# CLAUDE.md

## Keeping docs in sync

When a change touches the agent graph (nodes/edges), the API contract (request/response shapes, endpoints, SSE events), env vars/config, or the top-level project structure, update the relevant living docs in the same change: `README.md`, `CONTRIBUTING.md`, `CONTEXT.md`.

Do NOT edit `docs/PRD.md`, `docs/agent-hardening-backlog.md`, `docs/adr/*`, or `docs/build-log.md` to reflect the new state — these are frozen decision records of what was true/decided at the time, not living docs. "Frozen" means the decision and its rationale never change to match later reality. It does not exempt these docs from the plain-English voice below — an ADR's prose can and should be rewritten for readability, as long as the decision, the reasoning, and every fact stay exactly what was recorded at the time.

## Doc voice

Living docs (`README.md`, `CONTRIBUTING.md`, `CONTEXT.md`, `docs/data-pipeline.md`, `docs/corpus-receipts.md`) and the frozen `docs/adr/*` records must read as plain English — short sentences, no jargon-stacking, no nested clauses. Same text serves human readers and agents; don't write a "technical" version and a "readable" version. Concrete over abstract: name the file, the flag, the command, not "the relevant configuration."

That's the goal. These three checks are how you know you hit it — a rewrite that passes none of them is a reword, not a rewrite:

1. **One fact, one home.** Every flag, constraint, and number is stated in full in exactly one doc. Other docs state what it does in a sentence and link. `CONTRIBUTING.md` owns operator/dev detail (flags, commands, exact behavior). `CONTEXT.md` owns domain definitions. `README.md` owns highlights only — if a README paragraph restates a flag's full semantics, cut it to a sentence plus a link. This is where real length comes off.
2. **Count the words.** `wc -w` before and after. Restructuring prose usually moves the count a few percent; cutting duplication moves it 20%+. A rewrite that claims to simplify but barely moves the count didn't simplify anything.
3. **Diff for dropped facts.** Read the actual diff, not a summary of it. Removing a duplicate is the goal; removing the only copy of an endpoint, a safety invariant, or an env var is a regression. This has happened: a "verified" rewrite pass silently dropped `POST /receipts/telemetry` from the repo entirely.

Precision beats brevity when they conflict. Operational invariants ("amendment-only files are blockers, never base Acts", "never infer provenance", every fail-open rule) are load-bearing — an operator acts on them. Shorten the sentence around them; never cut the fact.

Run the `plain-english` skill before committing any doc change. It reviews the prose with a subagent that has no context on this project, which is the only reliable way to catch density you can no longer see in your own writing. The subagent flags passages; you decide which are filler and which are load-bearing, because it cannot tell the difference.

## Code comments

Comments explain **why**, not **what**. If a reader can't tell what a block does from the block itself, rename things or restructure it. Don't narrate it.

Write a comment when the code can't carry the reason on its own:

- Why this approach and not the obvious one (`maxsize=2` so the two flag variants never share a compiled agent).
- Why a number is that number (`RECURSION_LIMIT = 6` leaves room for two search rounds plus slack).
- A constraint from outside this file — a framework contract, an upstream bug, a fail-open rule an operator depends on.
- Why an empty `except` is correct, rather than that it's empty.

Delete a comment when it:

- restates the line below it
- describes machinery that lives in a library, not in this file
- tracks history the git log already holds ("we used to parse the message list")

Docstrings follow the same rule. Keep the part a caller can't infer — raising behavior, which caller owns the fail-open decision, what a non-obvious parameter is for. Drop the opening sentence that repeats the function name.

**Exception: text the model reads is behavior, not commentary.** Tool docstrings in `agent/retrieval/tools.py` become the tool schema sent to the LLM, and the system prompts in `agent/nodes/*.py` and `agent/retrieval/agent.py` steer the graph the same way. They describe what and when on purpose, at length, because that is what drives tool selection and routing. Never trim them for brevity. Changing them changes what the agent does, and the `tool_selection` evals will catch it.

## Build Log

Short notes on challenges and learnings. Full entries in `docs/build-log.md`.
