"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelEvalRun,
  EvalApiError,
  EvalCaseResult,
  EvalRunSummary,
  EvalSubset,
  fetchEvalCoverage,
  fetchEvalResults,
  flattenPersistedResult,
  streamEvalRun,
  type CoverageResponse,
  type GapFlag,
} from "@/lib/evalsTransport";

type PickerMode = "smoke" | "all" | "category" | "scenario" | "case_id";
type ResultSource = "cached" | "live" | "empty";

const palette = {
  ink: "#1e1d1a",
  muted: "#645f57",
  line: "#d8d0c2",
  page: "#f6f1e7",
  panel: "#fffdf8",
  panelSoft: "#eee7dc",
  accent: "#6e2f3a",
  accentSoft: "#eee0e1",
  pass: "#b8cdbd",
  passSoft: "#dfe9e1",
  partial: "#d7dde6",
  fail: "#d9aaad",
  failSoft: "#f1dddd",
  idle: "#e5ddcf",
  warning: "#9a5b47",
  warningSoft: "#f2dfd2",
};

function casePassed(result: EvalCaseResult) {
  return result.l1_failures.length === 0 && result.judge?.passed === true;
}

function caseFailureKind(result: EvalCaseResult) {
  if (result.l1_failures.length) return "L1";
  if (!result.judge?.passed) return "Judge";
  return "Pass";
}

function flagText(flag: GapFlag) {
  if (flag.rule === "thin_scenario") {
    return `${flag.scenario ?? `Category ${flag.category}`} has ${flag.count} cases; the coverage floor is ${flag.threshold}.`;
  }
  if (flag.rule === "weak_boundary_coverage") {
    return `Block cases are ${Math.round((flag.block_pct ?? 0) * 100)}% of the set; the boundary target is ${Math.round((flag.threshold ?? 0) * 100)}%.`;
  }
  return `${flag.scenario} has no smoke case, so CI cannot catch a regression there.`;
}

function cellColor(passed: number, total: number) {
  if (total === 0) return palette.idle;
  if (passed === total) return palette.pass;
  if (passed === 0) return palette.fail;
  return palette.partial;
}

function formatScenario(scenario: string) {
  return scenario.replaceAll("_", " ");
}

function CaseDetails({ result }: { result: EvalCaseResult }) {
  const kind = caseFailureKind(result);
  const passed = kind === "Pass";

  return (
    <details className="rounded-xl border" style={{ borderColor: palette.line, background: palette.panel }}>
      <summary className="grid cursor-pointer list-none grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 px-4 py-3">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
          style={{ background: passed ? palette.pass : palette.fail, color: palette.ink }}
        >
          {passed ? "✓" : "×"}
        </span>
        <span className="min-w-0">
          <span className="block font-mono text-xs font-semibold" style={{ color: palette.ink }}>{result.id}</span>
          <span className="mt-1 block truncate text-sm" style={{ color: palette.muted }}>{result.query}</span>
        </span>
        <span
          className="rounded-full px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.08em]"
          style={{ background: passed ? palette.passSoft : palette.failSoft, color: palette.ink }}
        >
          {kind}
        </span>
      </summary>

      <div className="grid gap-4 border-t px-4 py-4 text-sm lg:grid-cols-2" style={{ borderColor: palette.line }}>
        <div className="space-y-4">
          <DetailBlock title="Query"><p>{result.query}</p></DetailBlock>
          <DetailBlock title="Expected">
            <p>Policy: {result.expected_policy}</p>
            <p>Act {result.expected_act_number ?? "—"} · Section {result.expected_section ?? "—"}</p>
          </DetailBlock>
          <DetailBlock title="Actual citations">
            <p>{result.citations.length
              ? result.citations.map((citation) => `Act ${citation.act_number} §${citation.section_number}`).join(" · ")
              : "No citations returned"}</p>
          </DetailBlock>
        </div>
        <div className="space-y-4">
          <DetailBlock title="Agent response"><p className="whitespace-pre-wrap">{result.response || "No response"}</p></DetailBlock>
          <DetailBlock title="Deterministic checks">
            {result.l1_failures.length === 0
              ? <p>All applicable L1 checks passed.</p>
              : result.l1_failures.map((name) => (
                  <p key={name} style={{ color: palette.warning }}><code>{name}</code>: {result.l1_failure_details?.[name] ?? "Failed"}</p>
                ))}
          </DetailBlock>
          <DetailBlock title="LLM judge">
            <p>{result.judge
              ? `${result.judge.passed ? "PASS" : "FAIL"} — ${result.judge.reasoning ?? "No reasoning supplied."}`
              : "Not run because an L1 check failed."}</p>
          </DetailBlock>
        </div>
      </div>
    </details>
  );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>{title}</h4>
      <div className="space-y-1 leading-6" style={{ color: palette.muted }}>{children}</div>
    </div>
  );
}

function ResultMatrix({
  coverage,
  results,
  source,
  running,
  selectedScenario,
  onSelectScenario,
}: {
  coverage: CoverageResponse;
  results: EvalCaseResult[];
  source: ResultSource;
  running: boolean;
  selectedScenario: string | null;
  onSelectScenario: (scenario: string) => void;
}) {
  const scenarios = Object.keys(coverage.by_scenario);
  const byScenario = useMemo(() => {
    const grouped: Record<string, EvalCaseResult[]> = {};
    for (const scenario of scenarios) grouped[scenario] = [];
    for (const result of results) (grouped[result.scenario] ??= []).push(result);
    return grouped;
  }, [results, scenarios]);

  return (
    <div className="overflow-x-auto rounded-[20px] border p-4 shadow-[var(--shadow-raised)] md:p-5" style={{ borderColor: palette.line, background: palette.panel }}>
      <div className="min-w-[960px]">
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: `104px repeat(${scenarios.length}, minmax(128px, 1fr))` }}
        >
          <div />
          {scenarios.map((scenario, index) => (
            <div key={scenario} className="pb-2 text-center">
              <div className="font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>
                scenario {String(index + 1).padStart(2, "0")}
              </div>
              <div className="mt-1 text-lg font-bold capitalize" style={{ color: palette.ink }}>{formatScenario(scenario)}</div>
              <div className="mt-1 text-xs" style={{ color: palette.muted }}>{coverage.by_scenario[scenario]} dataset cases</div>
            </div>
          ))}

          <div className="flex items-center">
            <span
              className="rounded-full px-4 py-2 font-mono text-xs font-bold uppercase tracking-[0.08em]"
              style={{ background: source === "cached" ? palette.muted : palette.accent, color: palette.panel }}
            >
              {running ? "live" : source === "cached" ? "saved" : "latest"}
            </span>
          </div>

          {scenarios.map((scenario) => {
            const scenarioResults = byScenario[scenario] ?? [];
            const passed = scenarioResults.filter(casePassed).length;
            const active = selectedScenario === scenario;
            return (
              <button
                key={scenario}
                type="button"
                onClick={() => onSelectScenario(scenario)}
                className="min-h-[96px] rounded-xl border-2 px-2 py-2 text-center transition-transform hover:-translate-y-0.5"
                style={{
                  background: cellColor(passed, scenarioResults.length),
                  borderColor: active ? palette.ink : "transparent",
                  color: palette.ink,
                }}
                aria-label={`Inspect ${formatScenario(scenario)} results`}
              >
                {scenarioResults.length ? (
                  <>
                    <div className="font-mono text-[28px] font-bold leading-none">
                      {passed}<span className="text-base font-medium opacity-55">/{scenarioResults.length}</span>
                    </div>
                    <div className="mt-2 flex min-h-5 flex-wrap justify-center gap-x-2 gap-y-1 font-mono text-sm font-bold">
                      {scenarioResults.map((result) => (
                        <span key={result.id} title={`${result.id}: ${caseFailureKind(result)}`}>
                          {casePassed(result) ? "✓" : "×"}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="flex h-full min-h-[68px] items-center justify-center font-mono text-xs uppercase tracking-[0.08em]" style={{ color: palette.muted }}>
                    not run
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function EvalDashboard() {
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const [results, setResults] = useState<EvalCaseResult[]>([]);
  const [summary, setSummary] = useState<EvalRunSummary | null>(null);
  const [resultSource, setResultSource] = useState<ResultSource>("empty");
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [mode, setMode] = useState<PickerMode>("smoke");
  const [value, setValue] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [confirmArmed, setConfirmArmed] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([fetchEvalCoverage(), fetchEvalResults()])
      .then(([nextCoverage, report]) => {
        if (!alive) return;
        setCoverage(nextCoverage);
        if (report) {
          setResults(report.results.map(flattenPersistedResult));
          setSummary(report.summary);
          setResultSource("cached");
          setLastRunAt(report.generated_at);
        }
      })
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : "Unable to load eval dashboard"));
    return () => {
      alive = false;
      abortRef.current?.abort();
    };
  }, []);

  const subset = useMemo<EvalSubset>(() => {
    if (mode === "smoke" || mode === "all") return mode;
    return { [mode]: value } as EvalSubset;
  }, [mode, value]);

  const estimatedCount = useMemo(() => {
    if (!coverage) return 0;
    if (mode === "smoke") return coverage.smoke_cases;
    if (mode === "all") return coverage.total_cases;
    if (mode === "category") return coverage.by_category[value] ?? 0;
    if (mode === "scenario") return coverage.by_scenario[value] ?? 0;
    return value ? 1 : 0;
  }, [coverage, mode, value]);

  const displayedResults = selectedScenario
    ? results.filter((result) => result.scenario === selectedScenario)
    : results;
  const passedCount = results.filter(casePassed).length;
  const missingSections = coverage?.corpus_staleness.checked ? coverage.corpus_staleness.missing_sections : [];
  const invalidPicker = mode !== "smoke" && mode !== "all" && !value.trim();

  async function startRun() {
    if (estimatedCount > 20 && !confirmArmed) {
      setConfirmArmed(true);
      return;
    }
    setConfirmArmed(false);
    setError("");
    setResults([]);
    setSummary(null);
    setResultSource("live");
    setLastRunAt(null);
    setSelectedScenario(null);
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const event of streamEvalRun(subset, controller.signal)) {
        if (event.type === "run_start") setProgress(`Starting ${event.case_count} cases`);
        if (event.type === "case_start") setProgress(`${event.index}/${event.total} · ${event.id}`);
        if (event.type === "case_result") setResults((current) => [...current, event]);
        if (event.type === "run_summary") setSummary(event);
        if (event.type === "error") setError(event.message);
      }
      setLastRunAt(new Date().toISOString());
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (cause instanceof EvalApiError && cause.status === 422) {
          setError(`${cause.message}. Reseed the dedicated eval corpus before running.`);
        } else {
          setError(cause instanceof Error ? cause.message : "Eval run failed");
        }
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
      setProgress("");
    }
  }

  async function cancelRun() {
    await cancelEvalRun().catch(() => undefined);
    abortRef.current?.abort();
    setRunning(false);
    setProgress("");
  }

  if (!coverage) {
    return <main className="min-h-screen p-10" style={{ background: palette.page, color: palette.muted }}>Loading evaluation suite…</main>;
  }

  const corpusChecked = coverage.corpus_staleness.checked;

  return (
    <main className="min-h-screen" style={{ background: palette.page, color: palette.ink }}>
      <nav className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 md:px-8" style={{ borderColor: palette.line }}>
        <div className="flex items-center gap-3 text-lg font-bold">
          <span className="h-3 w-3 rounded-full" style={{ background: palette.accent }} />
          Locus eval studio
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full px-4 py-2 font-mono text-xs font-bold" style={{ background: palette.panel }}>n {results.length || "—"}</span>
          <span className="rounded-full px-4 py-2 font-mono text-xs font-bold uppercase" style={{ background: palette.panel }}>
            <span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: resultSource === "live" ? palette.accent : palette.muted }} />
            {running ? "live" : resultSource === "cached" ? "cached" : "ready"}
          </span>
        </div>
      </nav>

      <div className="mx-auto max-w-[1440px] space-y-6 px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-black tracking-[-0.04em] md:text-4xl">Evaluation suite</h1>
              <span className="rounded-full px-4 py-2 font-mono text-sm font-bold" style={{ background: palette.accent, color: palette.panel }}>latest</span>
            </div>
            <p className="mt-3 text-base" style={{ color: palette.muted }}>
              {coverage.total_cases} benchmark cases · {Object.keys(coverage.by_scenario).length} scenarios
              {lastRunAt ? ` · results ${resultSource === "cached" ? "saved" : "completed"} ${new Date(lastRunAt).toLocaleString()}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={cancelRun}
              disabled={!running}
              className="rounded-xl px-5 py-3 font-semibold disabled:opacity-45"
              style={{ background: palette.idle }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={startRun}
              disabled={running || invalidPicker || missingSections.length > 0}
              className="min-w-[160px] rounded-xl px-5 py-3 font-semibold disabled:opacity-45"
              style={{ background: palette.accent, color: palette.panel }}
            >
              {running ? `Running ${progress || "…"}` : confirmArmed ? "Confirm run" : `Run ${estimatedCount || ""} cases`}
            </button>
          </div>
        </header>

        <section className="rounded-xl border p-3" style={{ borderColor: palette.line, background: palette.panelSoft }} aria-label="Run configuration">
          <div className="grid gap-3 md:grid-cols-[220px_minmax(220px,1fr)_auto] md:items-center">
            <label className="flex items-center gap-3">
              <span className="font-mono text-[10px] font-bold uppercase tracking-[0.1em]" style={{ color: palette.muted }}>Run</span>
              <select
                value={mode}
                disabled={running}
                onChange={(event) => { setMode(event.target.value as PickerMode); setValue(""); setConfirmArmed(false); }}
                className="w-full rounded-xl border px-3 py-2.5 text-sm font-semibold"
                style={{ borderColor: palette.line, background: palette.panel }}
              >
                <option value="smoke">Smoke subset</option>
                <option value="all">All cases</option>
                <option value="category">By category</option>
                <option value="scenario">By scenario</option>
                <option value="case_id">Single case ID</option>
              </select>
            </label>

            <div>
              {mode === "category" && (
                <select value={value} onChange={(event) => setValue(event.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" style={{ borderColor: palette.line, background: palette.panel }}>
                  <option value="">Choose category…</option>
                  {Object.keys(coverage.by_category).map((category) => <option key={category}>{category}</option>)}
                </select>
              )}
              {mode === "scenario" && (
                <select value={value} onChange={(event) => setValue(event.target.value)} className="w-full rounded-xl border px-3 py-2.5 text-sm" style={{ borderColor: palette.line, background: palette.panel }}>
                  <option value="">Choose scenario…</option>
                  {Object.keys(coverage.by_scenario).map((scenario) => <option key={scenario}>{scenario}</option>)}
                </select>
              )}
              {mode === "case_id" && (
                <input value={value} onChange={(event) => setValue(event.target.value)} placeholder="evidence-90a-1" className="w-full rounded-xl border px-3 py-2.5 text-sm" style={{ borderColor: palette.line, background: palette.panel }} />
              )}
              {(mode === "smoke" || mode === "all") && (
                <p className="text-sm" style={{ color: palette.muted }}>
                  {mode === "smoke" ? "Fast signal across the CI-tagged cases." : "Complete benchmark; uses real model and judge tokens."}
                </p>
              )}
            </div>
            <div className="font-mono text-xs" style={{ color: palette.muted }}>{estimatedCount} selected</div>
          </div>
        </section>

        {confirmArmed && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.warningSoft }}>
            {estimatedCount} cases run the live agent and LLM judge, take roughly 5–8 minutes, and incur token cost. Click <strong>Confirm run</strong> to continue.
          </div>
        )}

        {missingSections.length > 0 && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.failSoft }}>
            <strong>Run blocked:</strong> the eval corpus is missing {missingSections.length} required sections. Reseed the dedicated eval database first.
          </div>
        )}
        {!corpusChecked && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.line, background: palette.panelSoft, color: palette.muted }}>
            Corpus status is not checked: {coverage.corpus_staleness.reason}. Coverage and saved results still work; a live run requires the eval database.
          </div>
        )}
        {error && <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.failSoft }} role="alert">{error}</div>}

        <section aria-labelledby="matrix-title">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>Result matrix</p>
              <h2 id="matrix-title" className="mt-1 text-2xl font-black">Pass rate by scenario</h2>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-xs" style={{ color: palette.muted }}>
              <span><b className="mr-1">✓</b> passed both gates</span>
              <span><b className="mr-1">×</b> failed L1 or judge</span>
              {summary && <span className="font-mono font-bold" style={{ color: palette.ink }}>{passedCount}/{results.length} overall</span>}
            </div>
          </div>
          <ResultMatrix
            coverage={coverage}
            results={results}
            source={resultSource}
            running={running}
            selectedScenario={selectedScenario}
            onSelectScenario={(scenario) => setSelectedScenario((current) => current === scenario ? null : scenario)}
          />
          <p className="mt-3 text-xs" style={{ color: palette.muted }}>Click a scenario cell to inspect only its cases below.</p>
        </section>

        <section className="grid gap-4 md:grid-cols-3" aria-label="How to use this dashboard">
          {[
            ["01", "Choose a subset", "Start with Smoke for a quick signal. Use All only when you want the full benchmark."],
            ["02", "Run and watch", "Each completed case adds a ✓ or × to its scenario cell while the run is live."],
            ["03", "Inspect failures", "Select a colored cell, then expand a failed case to see whether L1 or the judge rejected it."],
          ].map(([number, title, copy]) => (
            <div key={number} className="rounded-xl border p-4" style={{ borderColor: palette.line, background: palette.panelSoft }}>
              <span className="font-mono text-xs font-bold" style={{ color: palette.accent }}>{number}</span>
              <h3 className="mt-3 font-bold">{title}</h3>
              <p className="mt-2 text-sm leading-6" style={{ color: palette.muted }}>{copy}</p>
            </div>
          ))}
        </section>

        <section aria-labelledby="details-title" className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>Drill-down</p>
              <h2 id="details-title" className="mt-1 text-2xl font-black">
                {selectedScenario ? `${formatScenario(selectedScenario)} cases` : "All completed cases"}
              </h2>
            </div>
            {selectedScenario && (
              <button type="button" onClick={() => setSelectedScenario(null)} className="rounded-full px-4 py-2 text-xs font-semibold" style={{ background: palette.panel }}>Show all cases</button>
            )}
          </div>
          <div className="space-y-2">
            {displayedResults.map((result) => <CaseDetails key={result.id} result={result} />)}
            {displayedResults.length === 0 && (
              <div className="rounded-xl border border-dashed p-6 text-center text-sm" style={{ borderColor: palette.line, color: palette.muted }}>
                {results.length ? "No cases from this scenario were included in the run." : "Choose a subset and run it. Results will appear here as each case completes."}
              </div>
            )}
          </div>
        </section>

        <details className="rounded-xl border" style={{ borderColor: palette.line, background: palette.panelSoft }}>
          <summary className="cursor-pointer px-4 py-3 font-semibold">Dataset coverage and gaps</summary>
          <div className="grid gap-4 border-t px-4 py-4 lg:grid-cols-[1fr_1.4fr]" style={{ borderColor: palette.line }}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              {[
                ["Total", coverage.total_cases],
                ["Smoke", coverage.smoke_cases],
                ["Allow", coverage.by_policy.allow ?? 0],
                ["Block", coverage.by_policy.block ?? 0],
              ].map(([label, count]) => (
                <div key={label} className="rounded-xl p-4" style={{ background: palette.panel }}>
                  <div className="font-mono text-[10px] uppercase" style={{ color: palette.muted }}>{label}</div>
                  <div className="mt-1 text-2xl font-black">{count}</div>
                </div>
              ))}
            </div>
            <div className="space-y-2">
              {coverage.gap_flags.map((flag, index) => (
                <div key={`${flag.rule}-${flag.scenario ?? flag.category ?? index}`} className="rounded-xl px-4 py-3 text-sm" style={{ background: palette.warningSoft }}>{flagText(flag)}</div>
              ))}
            </div>
          </div>
        </details>
      </div>
    </main>
  );
}
