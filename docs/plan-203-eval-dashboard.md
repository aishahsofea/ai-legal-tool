# Plan: #203 eval dashboard, case browser and grounding set

Issue: https://github.com/aishahsofea/ai-legal-tool/issues/203

Each phase is one PR-sized diff. Stop for review after every phase. Land in order.

## Decisions taken (change any before phase 1 starts)

1. **Judge entry point.** The judge already labels each claim `supported`, `partial` or `unsupported` (`agent/nodes/grounding_check.py`, `_SYSTEM`). `grounding_check_node` only takes `AgentState` and returns violations. The runner needs the per-claim label. Phase 5 adds a small public function that returns the judge's raw per-claim output (label, quote, reason). The node calls it. The prompt, `GROUNDING_MODEL` and the Jev threshold stay untouched. The issue's "do not change grounding_check.py" means no behaviour change, and this is a pure extraction. If you disagree, the fallback is a fake `AgentState` in the runner, which is brittle.
2. **Match rule.** Judge label equals dataset `verdict` is a match. Otherwise a mismatch, shown as one of two kinds: judge too lenient (label `unsupported`, judge said `supported` or `partial`) or judge too strict (label `supported`, judge said `unsupported` or `partial`). Per #199 these cost differently.
3. **Jev cleared.** When Jev clears a claim, Ultra is not called, so there is no judge label. Record `jev_cleared: true` and treat the effective verdict as `supported`, the same as production does. Show it as "Jev cleared, judge skipped".
4. **Multi-select.** The runner gets `--case-ids a,b,c`. No temp files.
5. **Judgement-call field** is `judgement_call` (with `note`). Confirmed in `evals/validate_grounding_dataset.py:102`.
6. **#201 is merged** (PR #202). No blocker. The issue text is stale.
7. **Slices.** The issue's order (a, b, c) is split into six phases.

## Phase 1: eval set registry and per-set paths (backend, no UI)

- **Goal:** every endpoint can take a set name. The default is `end_to_end`, so nothing changes.
- **Files:** `api/evals.py`, `tests/test_evals_api.py`
- **Changes:**
  - Add a registry: set name, dataset path, results path, runner module. Only `end_to_end` is registered here.
  - Add `GET /evals/sets`.
  - Add an optional `set` query/body param on `/coverage`, `/run`, `/results`. An unknown set returns 404.
  - Keep `DATASET_PATH` and `RESULTS_PATH` as module names. Existing tests monkeypatch them. The end-to-end registry entry must read them at call time.
  - Results path per set: `evals/results/<set>.json`. Keep `evals/results.json` for `end_to_end` until phase 6 moves it (see "Open item").
- **Verify:** `pytest tests/test_evals_api.py tests/test_eval_dashboard.py` unchanged and green. New tests: `/sets`, unknown set gives 404, default set matches today's responses.

## Phase 2: case-list endpoint

- **Goal:** `GET /evals/cases?set=` returns every case with its fields, merged with the latest saved result and a status of `passed`, `failed` or `not run`.
- **Files:** `api/evals.py`, `tests/test_evals_api.py`
- **Changes:**
  - Per-set status function. For end-to-end it reuses the existing pass rule (no L1 failures and judge passed). The grounding status function is added in phase 5.
  - Merge by case id. Saved results with ids not in the dataset are ignored.
- **Verify:** new tests: no results file gives all `not run`. Partial results file gives a mix. Result with an unknown id is ignored. Smoke test against the real `evals/dataset.json` returns 80 cases.

## Phase 3: dashboard case browser, end-to-end set

- **Goal:** `/evals` lists every case before any run, with a set selector (one option for now) and a status badge. Opening a row shows the detail.
- **Files:** `frontend/lib/evalsTransport.ts`, `frontend/app/evals/EvalDashboard.tsx`, `tests/test_eval_dashboard.py`
- **Changes:**
  - Add `fetchEvalSets`, `fetchEvalCases`. Pass `set` through the existing fetch and stream helpers.
  - Add a case-list panel built from `/cases`. Rows show id, query, expected result, status. A not-run row has no answer, only the expected result.
  - Keep the scenario matrix. Feed it from the case list so scenarios with no run show every case, not just "not run".
  - Move `CaseDetails` behind a per-set detail component so phase 5 can add a grounding one.
- **Verify:** `test_eval_dashboard.py` (check how it tests the TSX today, and extend the same way). Manual: open `/evals`, see 80 rows before a run, see the same matrix as before after a run.

## Phase 4: run one or many from the case list

- **Goal:** per-row Run button and row multi-select. Run all, by scenario, and cancel keep working. The >20 confirm shows the case count.
- **Files:** `evals/run_evals.py`, `api/evals.py`, `frontend/lib/evalsTransport.ts`, `frontend/app/evals/EvalDashboard.tsx`, tests
- **Changes:**
  - `--case-ids a,b,c` in `run_evals.py` and a matching `case_ids` subset kind in `select_cases` (`evals/coverage.py`) and `runner_command`. Unknown ids give a 422.
  - Row Run button calls the existing stream with `{case_ids: [id]}`. Results merge into the list live.
  - The confirm text shows the case count. The threshold stays at 20.
  - Free-text "Single case ID" stays as is, or is removed if the row button makes it redundant. Ask at review.
- **Verify:** tests for `case_ids` selection, unknown id gives 422, `runner_command` output. Manual: run one case from its row, run three selected, cancel a run.

## Phase 5: grounding runner and judge entry point (backend)

- **Goal:** `evals/run_grounding.py` runs the real judge over claims and streams per-claim JSONL like `run_evals.py`.
- **Files:** `agent/nodes/grounding_check.py` (extraction only), `evals/jev_firstpass.py` (make helpers shared), new `evals/run_grounding.py`, `api/evals.py`, tests
- **Changes:**
  - Extract a public `judge_claims(draft, sources)` from the node. It returns the raw per-claim output. The node calls it, and behaviour is identical.
  - Move `_draft` and `_source` to a small shared module (or make them public in `jev_firstpass`). The runner and `jev_firstpass` both use them.
  - Runner: per claim, build the draft and source, run the Jev gate if `_jev_enabled()`, then run the judge. Emit `{id, label, judge_label, match, error_kind, jev_score, jev_cleared, reason, quote}` per line. It supports `--case-ids`, `--verdict`, `--language`, `--judgement-call`, `--limit`, `--jsonl`, `--output`. No DB needed.
  - Register the `grounding` set. `/run` skips the DB check and staleness for sets that don't need a corpus. Add a run summary for grounding (match rate, counts by error kind).
  - Grounding status function for `/cases`: `passed` means match, `failed` means mismatch.
- **Verify:**
  - Unit test for the runner with a stubbed judge and a stubbed Jev (match, both mismatch kinds, Jev cleared, Jev error falls through to the judge).
  - Existing grounding node tests unchanged and green. This is the check that the extraction changed no behaviour.
  - One real `--limit 3` run against the live judge. State its cost.
  - API test: `/evals/cases?set=grounding` returns 134, and counts by verdict are 56, 24, 54.

## Phase 6: grounding UI, filters, per-set results

- **Goal:** the grounding set is selectable and runnable from the dashboard, and results are saved per set.
- **Files:** `frontend/app/evals/EvalDashboard.tsx`, `frontend/lib/evalsTransport.ts`, `api/evals.py`, `tests/test_eval_dashboard.py`, `CONTRIBUTING.md`, `README.md` if its eval section changes
- **Changes:**
  - Set selector shows grounding. Grounding case detail shows the claim, source text, label, judge label, Jev score and cleared flag, quote, reason.
  - Filters: verdict, language, judgement-call. Mismatch styling differs for judge too lenient vs too strict.
  - Per-set results files. Running one set leaves the other's saved results untouched.
  - Count and confirm for grounding runs. Show the 134-call cost warning, not just the number.
  - Docs: set selector, `/evals/sets`, `/evals/cases`, `case_ids`, the grounding runner command, results paths. Run the `plain-english` skill and `wc -w` before and after, per `CLAUDE.md`.
- **Verify:** acceptance criteria from the issue, one by one:
  - Grounding shows 134 claims and the verdict filter shows 56, 24, 54.
  - Run one grounding case from its row and see label vs verdict.
  - Run grounding, then check `end_to_end` results are untouched, and the reverse.
  - Cancel a grounding run.
  - More than 20 cases needs a confirm that shows the count.
  - Both existing test files pass.

## Open item

`evals/results.json` is tracked and CI or docs may reference it. Phase 1 keeps it as the end-to-end path. Moving it to `evals/results/end_to_end.json` is optional. Do it in phase 6 only if nothing else reads the old path (`grep -rn results.json`).

## Out of scope (from the issue)

Changing the grounding prompt, model or threshold. Editing labels in the UI. New cases. Routing, commentary and reference-follow sets. Run history. Running from CI.

## Docs rule

Phases 1 to 5 add no user-facing behaviour beyond the API, so docs land in phase 6. If a phase is merged alone, move the matching doc lines into that phase instead.
