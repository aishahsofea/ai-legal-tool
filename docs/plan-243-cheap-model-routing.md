# Plan for #243: cheap model for simple queries

Issue: https://github.com/aishahsofea/ai-legal-tool/issues/243

Goal: faster answers at the same accuracy. Accuracy is the hard rule. Every phase is its own PR-sized diff. Stop for review after each one.

## Assumptions (open questions from the findings, not yet answered)

- The cheap model is a smaller Nemotron on Nebius. Name it in Phase 0.
- If `cross_act` has fewer than about 10 labelled cases, merge it into `multi_provision`. Report the merge.
- Metadata and the workflow map report the model that actually ran.
- The cheap model applies to the first pass only. A retry uses the strong model in both the synthesiser and the retrieval agent.
- Phase 0 stop bar: if synthesiser plus retrieval agent p50 on simple queries is under about 3s, stop and close with the numbers. Agree this number before Phase 0 ends.

## Phase 0: measure (no code)

- Goal: decide whether anything below is worth building.
- Work: from an existing eval run, split synthesiser and retrieval agent latency (p50, p95) and cost by query type. Source: the #188 usage block (`evals/usage.py`).
- Output: numbers posted as a comment on #243. Closing recommendation or go-ahead.
- Verify: numbers come from a real run, not list prices.
- Cost note: reuse an existing run if one has the split. A new run needs a time and dollar estimate first.

## Phase 1: report two models per node

- Goal: make the code able to say "this node ran model X" per call. Behaviour does not change.
- Files: `agent/llm_factory.py`, `agent/query_lifecycle.py`, `agent/retrieval/agent.py`, `agent/nodes/synthesiser.py`, `api/evals.py`.
- Changes:
  - `_NODE_MODELS` holds a list of models per node. `node_models()` keeps working for single-model nodes.
  - `node_model_event` for the synthesiser uses the model that ran, not the `_MODEL` constant.
  - LangSmith metadata and the workflow map read the new shape.
- Verify: existing tests pass. New tests: metadata, retrieval event and workflow map each with one model and with two.

## Complexity rubric

Used to label `evals/routing_dataset.json` and to write the Jev question in Phase 2. One rule: count the sections the answer must cite, and the Acts they sit in.

- `simple`: one section, or one concept with one home. The cheap model answers these.
  - Names one section of one Act, or asks for its text.
  - Asks about one concept that lives in one section, such as stalking or when wages are due.
  - Asks for a definitions list. The interpretation section is one section, even when it is long.
  - Asks "which Act covers X" and one Act clearly owns X, such as workplace safety (OSHA). Data protection, workplace harassment and tenancy have no single owner, so they are `multi_provision`.
  - A follow-up that resolves to one section from history.
- `multi_provision`: two or more sections, or two or more Acts. The strong model answers these.
  - Says "all", "every" or "list all" over an Act: penalties, offences, powers.
  - Asks how provisions interact, or which provisions could apply.
  - Asks about a right that needs a sibling section, such as access and correction under the PDPA.
  - Asks whether an Act applies, which needs the scope section and the definitions.
  - Asks "which laws cover X" and several Acts plausibly do. This is the old `cross_act` case, folded in.
- Tie-break: if unsure, label `multi_provision`. A wrong `simple` sends a hard question to the cheap model. A wrong `multi_provision` only costs money.
- Not labelled: `clarify` and `conversational` cases never reach retrieval.

## Phase 2: Jev complexity question

- Goal: the router returns `complexity` and its probability. Nothing uses it yet.
- Files: `agent/nodes/router_jev.py`, `agent/nodes/router.py`, `agent/state.py`.
- Changes:
  - Third question in `QUESTIONS`: `simple`, `multi_provision`, `cross_act`. Write the criteria once. Do not reword after measuring.
  - `jev_route` returns complexity and probability. `_jev_result` puts them in state.
  - LLM-router path and Jev errors leave the fields unset.
- Verify: unit tests for parse, unknown choice, missing probability, out-of-range probability. Re-run the routing eval and confirm `query_type` and language accuracy did not drop.

## Phase 3: label the routing dataset and report accuracy

- Goal: know whether Jev can tell simple from hard.
- Files: `evals/routing_dataset.json`, `evals/validate_routing_dataset.py`, `evals/run_routing.py`, `evals/routing_summary.py`.
- Changes: hand-label expected complexity on the legal cases. Report accuracy and mean probability per class, with n per class. Mark any class under about 10 as too small to trust.
- Verify: validator accepts the labels. Summary prints per-class numbers.
- Decision point: merge `cross_act` into `multi_provision` if it is too small.

## Phase 4: per-call model selection behind a flag

- Goal: pick strong or cheap per call. Flag off means today's behaviour exactly.
- Files: `agent/feature_flags.py`, `agent/llm_factory.py`, `agent/nodes/synthesiser.py`, `agent/retrieval/agent.py`, `.env.example`.
- Changes:
  - New flag and cheap-model env vars for each node.
  - Synthesiser holds a strong and a cheap structured LLM. Retrieval agent cache key includes the model.
  - Rule: cheap only when the flag is on, complexity is `simple`, probability is at or above the threshold, and `retry_count` is 0. Anything else is strong.
  - Threshold env var follows the `grounding_check.py` pattern. Unset or invalid takes the strictest value, so the gate is never loosened.
  - Check the Ultra prefix-cache salt and `_StructuredLLM` workarounds against the cheap model name.
- Verify: unit tests for Jev error, LLM-router fallback, low probability, retry, and flag off. All five choose or keep the strong model.

## Phase 5: eval comparison on simple cases

- Goal: show cheap matches strong on accuracy, and measure the time saved.
- Files: eval scripts as needed. Output goes in the issue.
- Changes: run `simple` cases on both models. Compare citation accuracy, grounding pass rate, p50 and p95 latency per node, dollar cost, and the retry rate on cheap drafts with its added time.
- Verify: results come from the #188 usage block, stated as ranges. No list prices.
- Cost note: give time and dollars before the run (earlier A/B runs cost about $1.50 each). Use `--smoke` to iterate.
- Decision point: if cheap is not within noise on accuracy, or retries erase the saving, close the issue with the numbers and leave the flag off.

## Phase 6: choose the threshold and write docs

- Goal: set the default threshold from Phases 3 and 5, then document.
- Files: `agent/` default constant, `CONTRIBUTING.md`, `.env.example`, `CONTEXT.md` if "complexity" becomes a domain term.
- Changes: pick the threshold that minimises expected latency with accuracy held equal, counting retry cost. Document the flag, the threshold and the rule.
- Verify: threshold tests. Run the `plain-english` skill on the doc changes.
- Out of scope: turning the flag on in production.

## Order

0 → 1 → 2 → 3 → 4 → 5 → 6. Phase 1 must land before Phase 4. Phase 3 must land before Phase 5, so the comparison uses cases the router would really send down each path. Phase 0 can end the whole plan.
