# Agentic retrieval via LLM tool-calling

Date: 2026-07-11

Retrieval is done by an LLM that binds two tools — `search_statutes` (semantic pgvector search) and `lookup_section` (exact section lookup) — and **decides** which to call, with what arguments, and whether to search again, replacing the fixed "if `statute_lookup` try exact-lookup else vector search" dispatch in the retriever node. The agent is a LangGraph `create_react_agent`. The whole path is gated behind `AGENTIC_RETRIEVAL` (off by default) and **fails open** to the deterministic retriever. A second change rides on the same tool loop: an evidence-shaped supervision failure now **re-retrieves** with feedback instead of only re-drafting.

## Context

Every LLM node in the graph used `.with_structured_output()`; the graph was a fixed state machine. There was no `bind_tools` / `ToolNode` / `create_react_agent` anywhere. The deterministic retriever hard-coded its strategy: exact lookup only for `router`-labelled `statute_lookup` queries, vector search otherwise, with fixed `top_k` and no filters on the vector path. Three agent-hardening-backlog items pointed at the same gap — "exact statute lookup bypassing embeddings," "query-type-specific retrieval strategies," and "bounded query rewriting on retrieval miss" — each a hand-written branch we would otherwise keep adding to the dispatch.

The retry loop had a matching blind spot: any supervision failure (`citation_validator`, `grounding_check`, or `supervisor`) re-ran the **synthesiser** against the **same** retrieved chunks. When the real problem was missing evidence — a cited section that was never retrieved, or a claim no retrieved section supports — re-drafting the same context could not fix it; it just spent the retry and failed closed.

This project is also a portfolio artifact for agent-engineering roles whose bar is explicitly tool-calling reliability and agent supervision. A fixed pipeline cannot demonstrate either.

## Decisions

- **The retriever becomes a ReAct agent, built with `create_react_agent`.** It binds `search_statutes(query, top_k, act, language)` and `lookup_section(section, act)`. The model chooses the tool and arguments and may call again (e.g. reformulate after a weak `search_statutes`, or fall back to search after a `lookup_section` miss). The loop is bounded by `recursion_limit` (default 6). We use the prebuilt rather than a hand-rolled loop: the Reason→Act→observe loop, the `tool_calls` routing, and the `ToolMessage` plumbing are standard and not where this project's value lies.
- **Tools own the search layer, decoupled from the node.** `agent/retrieval/search.py` holds `semantic_search` / `exact_section_lookup` (extracted from the old node, each managing its own connection); `agent/retrieval/tools.py` wraps them as `@tool`s. The same functions back the deterministic node, so both paths return the identical chunk-dict shape and downstream nodes are unchanged.
- **Tools write chunks into agent state via `Command(update=...)`, not `ToolMessage` text.** A custom `RetrievalState` adds a `retrieved_chunks` channel with a case-insensitive dedupe reducer, so overlapping searches accumulate cleanly and the wrapper reads the rows back losslessly instead of parsing tool-message strings.
- **Off by default, fail-open.** `AGENTIC_RETRIEVAL` selects the node at graph-build time; the wrapper falls back to the deterministic retriever on any exception or empty result. Turning the flag on can never retrieve less than the proven path. This mirrors the `SEMANTIC_MEMORY_*` dark-launch convention.
- **Tool calls are observable.** Each tool emits a custom-stream event; because a manually-invoked sub-agent's stream doesn't bubble to the parent graph, the wrapper streams the sub-agent and re-emits each event through the parent writer. `run_query_stream` turns these into a new `tool_call` SSE event, rendered as steps in the frontend PROCESS panel.
- **The retry routes by violation kind (re-retrieval).** `citation_validator` and `grounding_check` tag their evidence-shaped findings into a separate `evidence_violations` list; `supervisor` policy checks do not. On an evidence gap — and only when the flag is on — the retry runs a new `retry_retrieve` node that re-invokes the agent with feedback built from the gap, then re-enters `retriever → recall → synthesiser`. Policy/phrasing violations still re-draft. The retry budget is unchanged (`MAX_RETRIES = 1`): one *smarter* retry, not more loops. An evidence gap that survives re-retrieval still fails closed.
- **Structured output stays on the synthesiser.** Tool-calling and structured output are mutually exclusive per model instance; they live on different nodes, so there is no conflict. Only retrieval became tool-calling.
- **Evals gain a `tool_selection` L1 assertion.** Dataset cases may declare `expected_tool`; a `tool_trace` is plumbed out of `run_query`. The assertion activates only when the flag is on (the deterministic path produces no trace), so the default CI eval is unaffected.

## Considered options

- **Hand-roll the ReAct loop with `ToolNode` + `tools_condition`.** Rejected for this change. More educational per line, but the prebuilt is the industry-standard boundary and the loop mechanics aren't the risk here. Documented how it works (README) so the abstraction isn't a black box.
- **Add the agent as a subgraph *node* in the parent graph.** Automatic stream propagation, but it forces a state-schema mapping between `AgentState` and the react agent's `MessagesState`, and complicates the fail-open fallback. Rejected in favour of a thin wrapper that invokes a self-contained compiled agent and keeps the existing `{"retrieved_chunks": ...}` interface.
- **Return chunks as `ToolMessage` text and re-parse.** Rejected — lossy and fragile. `Command`-into-custom-state is the current idiom.
- **More retry budget for re-retrieval.** Rejected. Re-retrieval is expensive; one smarter retry preserves the cost/latency envelope and the fail-closed guarantee.
- **Keep the fixed dispatch and just add filters.** Rejected. It defers the same backlog items and demonstrates none of the tool-calling the project exists to show.

## Consequences

- **The three retrieval-strategy backlog items are closed** by one mechanism instead of accreting branches: the model picks exact vs semantic, sets `top_k`/filters, and reformulates on a miss.
- **Evidence failures can now actually be repaired**, not just re-drafted — the retry fetches different sources with feedback. The failure surface is narrower without weakening the fail-closed floor.
- **New cost/latency on the agentic path.** The ReAct loop adds LLM calls (an extra `RETRIEVAL_AGENT_MODEL` round-trip or two per turn) versus the single deterministic search. Acceptable because it is opt-in and bounded; the deterministic path remains the default.
- **A dark-launch surface to validate.** The flag is off in CI; correctness is checked by the flag-gated `tool_selection` assertion and a flag-on smoke run, and the deterministic suite stays green with the flag unset.
- **Re-retrieval replaces rather than merges chunks.** A re-retrieval pass overwrites `retrieved_chunks` (no parent-level reducer); the feedback is expected to re-surface the good sources. Accepted as a simpler, predictable bound for a single retry.
- **Living docs updated** (README graph + SSE contract, CONTRIBUTING env flags + model table, CONTEXT language). Prior ADRs, the PRD, the backlog, and earlier build-log entries are left as frozen records.

## Related

- ADR 0003 — Python / LangGraph agent runtime (the graph this restructures the retrieval slice of).
- ADR 0007 — history-aware retrieval (the `Standalone Query` the agent searches on).
- ADR 0011 — citation validation over structured data (the evidence signal that now drives re-retrieval).
- Agent hardening backlog — "exact statute lookup bypassing embeddings," "query-type-specific retrieval strategies," "bounded query rewriting on retrieval miss"; this ADR is those items.
