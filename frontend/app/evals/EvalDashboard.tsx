"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelEvalRun,
  EvalApiError,
  EvalCaseResult,
  EvalRunSummary,
  EvalSubset,
  fetchEvalCases,
  fetchEvalCoverage,
  fetchEvalResults,
  fetchEvalSets,
  flattenPersistedResult,
  isGroundingResult,
  isGroundingSummary,
  streamEvalRun,
  type CoverageResponse,
  type EvalCaseRow,
  type GapFlag,
  type GroundingCoverage,
  type GroundingErrorKind,
  type GroundingLabel,
  type GroundingResult,
  type GroundingSummary,
} from "@/lib/evalsTransport";
import { palette } from "./palette";
import { Play, Spinner, Stop } from "./icons";
import { Select } from "./Select";
import { addResult, emptyTally, outcomeText, toOutcome, withTotal, type RunOutcome, type RunTally } from "./runOutcome";

type PickerMode = "smoke" | "all" | "language" | "category" | "scenario" | "case_id";

// The bilingual baseline runs BM and code-switched cases together, so it is one
// option rather than two separate runs.
const BILINGUAL_SUBSET = "bm,mixed";

const RUN_MODES: { value: PickerMode; label: string }[] = [
  { value: "smoke", label: "Smoke subset" },
  { value: "all", label: "All cases" },
  { value: "language", label: "By language" },
  { value: "category", label: "By category" },
  { value: "scenario", label: "By scenario" },
  { value: "case_id", label: "Single case ID" },
];

const asOption = (name: string) => ({ value: name, label: name });
type ResultSource = "cached" | "live" | "empty";

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

function formatSectionRef(entry: { act_number: string; section_number: string }) {
  return `Act ${entry.act_number} §${entry.section_number}`;
}

// A ring rather than a thicker border, so the row does not shift when it activates.
function rowStyle(active: boolean) {
  return {
    borderColor: active ? palette.accent : palette.line,
    background: palette.panel,
    boxShadow: active ? `0 0 0 1px ${palette.accent}` : undefined,
  };
}

function ActiveMark() {
  return (
    <>
      <Spinner />
      <span className="sr-only">running</span>
    </>
  );
}

function CaseDetails({ result, active }: { result: EvalCaseResult; active: boolean }) {
  const kind = caseFailureKind(result);
  const passed = kind === "Pass";

  return (
    <details className="rounded-xl border" style={rowStyle(active)}>
      <summary className="grid cursor-pointer list-none grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 px-4 py-3">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
          style={active ? { background: palette.accentSoft, color: palette.accent } : { background: passed ? palette.pass : palette.fail, color: palette.ink }}
        >
          {active ? <ActiveMark /> : passed ? "✓" : "×"}
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
        <div className="flex flex-col gap-5">
          <DetailBlock title="Query"><p>{result.query}</p></DetailBlock>
          <DetailBlock title="Expected">
            <p>Policy: {result.expected_policy}</p>
            {result.section_recall ? (
              <>
                <p>
                  Sections found: {result.section_recall.matched}/{result.section_recall.expected}
                  {" "}({Math.round(result.section_recall.recall * 100)}%)
                </p>
                <p>
                  Missing: {result.section_recall.missing_sections.length
                    ? result.section_recall.missing_sections.map(formatSectionRef).join(" · ")
                    : "none"}
                </p>
              </>
            ) : (
              <p>Act {result.expected_act_number ?? "—"} · Section {result.expected_section ?? "—"}</p>
            )}
          </DetailBlock>
          <DetailBlock title="Actual citations">
            <p>{result.citations.length
              ? result.citations.map(formatSectionRef).join(" · ")
              : "No citations returned"}</p>
          </DetailBlock>
        </div>
        <div className="flex flex-col gap-5">
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

const GROUNDING_LABELS: GroundingLabel[] = ["supported", "partial", "unsupported"];

// The two mismatch kinds cost differently: too lenient lets an unsupported claim
// through, too strict blocks a sound one.
const ERROR_KIND_STYLE: Record<GroundingErrorKind, { label: string; bg: string; fill: string }> = {
  too_lenient: { label: "judge too lenient", bg: palette.failSoft, fill: palette.fail },
  too_strict: { label: "judge too strict", bg: palette.warningSoft, fill: palette.partial },
};

function groundingBadge(result: GroundingResult) {
  if (result.error) return { text: "judge error", bg: palette.warningSoft, fill: palette.partial, mark: "!" };
  if (result.match) return { text: "match", bg: palette.passSoft, fill: palette.pass, mark: "✓" };
  const kind = ERROR_KIND_STYLE[result.error_kind ?? "too_strict"];
  return { text: kind.label, bg: kind.bg, fill: kind.fill, mark: "×" };
}

function judgeLabelText(result: GroundingResult) {
  if (result.error) return "none (judge call failed)";
  if (result.jev_cleared) return `${result.judge_label} (Jev cleared, judge skipped)`;
  return result.judge_label ?? "none";
}

function GroundingDetails({ row, result, active }: { row: EvalCaseRow; result: GroundingResult | undefined; active: boolean }) {
  const badge = result
    ? groundingBadge(result)
    : { text: "not run", bg: palette.idle, fill: palette.idle, mark: "·" };
  return (
    <details className="rounded-xl border" style={rowStyle(active)}>
      <summary className="grid cursor-pointer list-none grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 px-4 py-3">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
          style={active ? { background: palette.accentSoft, color: palette.accent } : { background: badge.fill, color: palette.ink }}
        >
          {active ? <ActiveMark /> : badge.mark}
        </span>
        <span className="min-w-0">
          <span className="block font-mono text-xs font-semibold" style={{ color: palette.ink }}>
            {row.id} · {row.language} · expects {row.verdict}{row.judgement_call ? " · judgement call" : ""}
          </span>
          <span className="mt-1 block truncate text-sm" style={{ color: palette.muted }}>{row.claim}</span>
        </span>
        <span className="rounded-full px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.08em]" style={{ background: badge.bg, color: palette.ink }}>
          {result?.judge_label ? `${result.judge_label}${result.jev_cleared ? " · jev" : ""}` : badge.text}
        </span>
      </summary>

      <div className="grid gap-4 border-t px-4 py-4 text-sm lg:grid-cols-2" style={{ borderColor: palette.line }}>
        <div className="flex flex-col gap-5">
          <DetailBlock title="Claim"><p>{row.claim}</p></DetailBlock>
          <DetailBlock title={`Source · ${row.act_title} §${row.section_number}`}>
            <p>{row.source_text}</p>
          </DetailBlock>
          {row.judgement_call && (
            <DetailBlock title="Judgement call"><p>{row.note || "Flagged as a judgement call."}</p></DetailBlock>
          )}
        </div>
        <div className="flex flex-col gap-5">
          <DetailBlock title="Label vs judge">
            <p>Dataset label: <b>{row.verdict}</b></p>
            {result ? (
              <>
                <p>Judge label: <b>{judgeLabelText(result)}</b></p>
                <p style={{ color: result.match ? palette.muted : palette.warning }}>
                  {result.error ? "No comparison: the judge call failed." : result.match ? "Match." : `Mismatch: ${ERROR_KIND_STYLE[result.error_kind ?? "too_strict"].label}.`}
                </p>
              </>
            ) : <p>Not run yet.</p>}
          </DetailBlock>
          {result && (
            <>
              <DetailBlock title="Jev first pass">
                <p>
                  Score: {result.jev_score === null ? "—" : result.jev_score.toFixed(3)}
                  {" · "}cleared: {result.jev_cleared ? "yes" : "no"}
                  {result.jev_error ? " · Jev errored, fell through to the judge" : ""}
                </p>
              </DetailBlock>
              {result.quote && <DetailBlock title="Judge quote"><p className="whitespace-pre-wrap">{result.quote}</p></DetailBlock>}
              <DetailBlock title="Judge reason">
                <p className="whitespace-pre-wrap" style={result.error ? { color: palette.warning } : undefined}>
                  {result.error || result.reason || "No reason supplied."}
                </p>
              </DetailBlock>
            </>
          )}
        </div>
      </div>
    </details>
  );
}

// Dataset label (rows) against judge label (columns). A Jev-cleared claim counts as supported, as in production.
function GroundingMatrix({ rows, results }: { rows: EvalCaseRow[]; results: Record<string, GroundingResult> }) {
  const counts: Record<string, number> = {};
  for (const row of rows) {
    const judged = results[row.id]?.judge_label;
    if (judged) counts[`${row.verdict}:${judged}`] = (counts[`${row.verdict}:${judged}`] ?? 0) + 1;
  }
  return (
    <div className="overflow-x-auto rounded-[20px] border p-4 md:p-5" style={{ borderColor: palette.line, background: palette.panel }}>
      <table className="w-full min-w-[420px] border-separate border-spacing-2 text-center text-sm">
        <thead>
          <tr className="font-mono text-[10px] uppercase tracking-[0.1em]" style={{ color: palette.muted }}>
            <th className="text-left">dataset ↓ · judge →</th>
            {GROUNDING_LABELS.map((label) => <th key={label}>{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {GROUNDING_LABELS.map((verdict) => (
            <tr key={verdict}>
              <th className="text-left font-mono text-xs" style={{ color: palette.ink }}>{verdict}</th>
              {GROUNDING_LABELS.map((judged) => {
                const count = counts[`${verdict}:${judged}`] ?? 0;
                const rank = (label: string) => GROUNDING_LABELS.length - GROUNDING_LABELS.indexOf(label as GroundingLabel);
                const background = count === 0 ? palette.idle
                  : verdict === judged ? palette.pass
                  : rank(judged) > rank(verdict) ? ERROR_KIND_STYLE.too_lenient.fill : ERROR_KIND_STYLE.too_strict.fill;
                return (
                  <td key={judged} className="rounded-lg py-3 font-mono text-xl font-bold" style={{ background, color: palette.ink }}>{count}</td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Per-set seam: each set renders its own detail component.
function CaseRowDetail({ row, result, grounding, active }: {
  row: EvalCaseRow;
  result: EvalCaseResult | undefined;
  grounding: GroundingResult | undefined;
  active: boolean;
}) {
  if (row.claim !== undefined) return <GroundingDetails row={row} result={grounding} active={active} />;
  if (result) return <CaseDetails result={result} active={active} />;
  return <NotRunRow row={row} active={active} />;
}

function NotRunRow({ row, active }: { row: EvalCaseRow; active: boolean }) {
  return (
    <div className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl border px-4 py-3" style={rowStyle(active)}>
      <span
        className="flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold"
        style={active ? { background: palette.accentSoft, color: palette.accent } : { background: palette.idle, color: palette.muted }}
      >
        {active ? <ActiveMark /> : "·"}
      </span>
      <span className="min-w-0">
        <span className="block font-mono text-xs font-semibold" style={{ color: palette.ink }}>{row.id}</span>
        <span className="mt-1 block truncate text-sm" style={{ color: palette.muted }}>{row.query}</span>
        <span className="mt-1 block font-mono text-[11px]" style={{ color: palette.muted }}>
          expects {row.expected_policy ?? "allow"} · Act {row.expected_act_number ?? "—"} · Section {row.expected_section ?? "—"}
        </span>
      </span>
      <span className="rounded-full px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.08em]" style={{ background: palette.idle, color: palette.ink }}>
        {active ? "running" : "not run"}
      </span>
    </div>
  );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t pt-4 first:border-t-0 first:pt-0" style={{ borderColor: palette.line }}>
      <h4 className="mb-2 text-sm font-bold" style={{ color: palette.ink }}>{title}</h4>
      <div className="space-y-1 leading-6" style={{ color: palette.muted }}>{children}</div>
    </div>
  );
}

function ResultMatrix({
  coverage,
  cases,
  resultsById,
  source,
  running,
  activeCaseId,
  selectedScenario,
  onSelectScenario,
}: {
  coverage: CoverageResponse;
  cases: EvalCaseRow[];
  resultsById: Record<string, EvalCaseResult>;
  source: ResultSource;
  running: boolean;
  activeCaseId: string | null;
  selectedScenario: string | null;
  onSelectScenario: (scenario: string) => void;
}) {
  const scenarios = Object.keys(coverage.by_scenario);
  // Every dataset case sits in its scenario cell; a case with no result is a
  // `null` slot, so a partial run still shows the cases it did not cover.
  const byScenario = useMemo(() => {
    const grouped: Record<string, { id: string; result: EvalCaseResult | null }[]> = {};
    for (const scenario of scenarios) grouped[scenario] = [];
    for (const row of cases) {
      (grouped[row.scenario ?? ""] ??= []).push({ id: row.id, result: resultsById[row.id] ?? null });
    }
    return grouped;
  }, [cases, resultsById, scenarios]);

  return (
    <div className="rounded-[20px] border p-4 shadow-[var(--shadow-raised)]" style={{ borderColor: palette.line, background: palette.panel }}>
        <div
          className="grid gap-3"
          style={{ gridTemplateColumns: `auto repeat(${scenarios.length}, minmax(0, 1fr))` }}
        >
          <div />
          {scenarios.map((scenario, index) => (
            <div key={scenario} className="pb-1 text-center">
              <div className="text-sm font-bold capitalize leading-tight" style={{ color: palette.ink }}>{formatScenario(scenario)}</div>
              <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.08em]" style={{ color: palette.muted }}>
                scenario {String(index + 1).padStart(2, "0")} · {coverage.by_scenario[scenario]} dataset cases
              </div>
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
            const slots = byScenario[scenario] ?? [];
            const ran = slots.filter((slot) => slot.result);
            const passed = ran.filter((slot) => casePassed(slot.result!)).length;
            const active = selectedScenario === scenario;
            const hasActiveCase = activeCaseId !== null && slots.some((slot) => slot.id === activeCaseId);
            return (
              <button
                key={scenario}
                type="button"
                onClick={() => onSelectScenario(scenario)}
                className="relative min-h-[64px] rounded-xl border-2 px-2 py-1 text-center transition-transform hover:-translate-y-0.5"
                style={{
                  background: cellColor(passed, ran.length),
                  borderColor: active ? palette.ink : "transparent",
                  color: palette.ink,
                }}
                aria-label={`Inspect ${formatScenario(scenario)} results${hasActiveCase ? " (case running)" : ""}`}
              >
                {hasActiveCase && (
                  <span
                    aria-hidden
                    className="pointer-events-none absolute -inset-0.5 rounded-xl motion-safe:animate-pulse"
                    style={{ boxShadow: `0 0 0 3px ${palette.accent}` }}
                  />
                )}
                {ran.length || hasActiveCase ? (
                  <>
                    <div className="font-mono text-xl font-bold leading-none">
                      {passed}<span className="text-base font-medium opacity-55">/{slots.length}</span>
                    </div>
                    <div className="mt-1 flex min-h-5 flex-wrap justify-center gap-x-2 gap-y-1 font-mono text-sm font-bold">
                      {slots.map(({ id, result }) => (
                        <span key={id} title={`${id}: ${id === activeCaseId ? "running" : result ? caseFailureKind(result) : "not run"}`}>
                          {id === activeCaseId ? "…" : result ? (casePassed(result) ? "✓" : "×") : "·"}
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="flex h-full min-h-[48px] items-center justify-center font-mono text-xs uppercase tracking-[0.08em]" style={{ color: palette.muted }}>
                    not run
                  </div>
                )}
              </button>
            );
          })}
        </div>
    </div>
  );
}

export default function EvalDashboard() {
  const [sets, setSets] = useState<string[]>([]);
  const [set, setSet] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<CoverageResponse | GroundingCoverage | null>(null);
  const [cases, setCases] = useState<EvalCaseRow[]>([]);
  const [resultsById, setResultsById] = useState<Record<string, EvalCaseResult>>({});
  const [summary, setSummary] = useState<EvalRunSummary | null>(null);
  const [groundingById, setGroundingById] = useState<Record<string, GroundingResult>>({});
  const [groundingSummary, setGroundingSummary] = useState<GroundingSummary | null>(null);
  const [verdictFilter, setVerdictFilter] = useState("");
  const [languageFilter, setLanguageFilter] = useState("");
  const [judgementOnly, setJudgementOnly] = useState(false);
  const [resultSource, setResultSource] = useState<ResultSource>("empty");
  const [lastRunAt, setLastRunAt] = useState<string | null>(null);
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [mode, setMode] = useState<PickerMode>("smoke");
  const [value, setValue] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [confirmArmed, setConfirmArmed] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  // Refs, not state: cancelRun reads the tally while startRun's stream loop is mid-flight.
  const tallyRef = useRef<RunTally>(emptyTally);
  const cancelledRef = useRef(false);

  useEffect(() => {
    let alive = true;
    fetchEvalSets()
      .then((response) => {
        if (!alive) return;
        setSets(response.sets.map((entry) => entry.name));
        setSet(response.default);
      })
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : "Unable to load eval dashboard"));
    return () => {
      alive = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!set) return;
    let alive = true;
    Promise.all([fetchEvalCoverage(set), fetchEvalCases(set), fetchEvalResults(set)])
      .then(([nextCoverage, rows, report]) => {
        if (!alive) return;
        setCoverage(nextCoverage);
        setMode("by_verdict" in nextCoverage ? "all" : "smoke");
        setCases(rows);
        const saved: Record<string, EvalCaseResult> = {};
        const savedGrounding: Record<string, GroundingResult> = {};
        for (const row of rows) {
          if (!row.result) continue;
          if (isGroundingResult(row.result)) savedGrounding[row.id] = row.result;
          else saved[row.id] = flattenPersistedResult(row.result);
        }
        setResultsById(saved);
        setGroundingById(savedGrounding);
        const savedSummary = report?.summary ?? null;
        setSummary(savedSummary && !isGroundingSummary(savedSummary) ? savedSummary : null);
        setGroundingSummary(savedSummary && isGroundingSummary(savedSummary) ? savedSummary : null);
        setResultSource(report ? "cached" : "empty");
        setLastRunAt(report?.generated_at ?? null);
      })
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : "Unable to load eval dashboard"));
    return () => {
      alive = false;
    };
  }, [set]);

  const subset = useMemo<EvalSubset>(() => {
    if (mode === "smoke" || mode === "all") return mode;
    return { [mode]: value } as EvalSubset;
  }, [mode, value]);

  const estimatedCount = useMemo(() => {
    if (!coverage) return 0;
    if (!("by_scenario" in coverage)) return mode === "all" ? coverage.total_cases : 0;
    if (mode === "smoke") return coverage.smoke_cases;
    if (mode === "all") return coverage.total_cases;
    if (mode === "category") return coverage.by_category[value] ?? 0;
    if (mode === "scenario") return coverage.by_scenario[value] ?? 0;
    if (mode === "language") {
      return value
        .split(",")
        .reduce((total, language) => total + (coverage.by_language[language.trim()] ?? 0), 0);
    }
    return value ? 1 : 0;
  }, [coverage, mode, value]);

  const results = useMemo(
    () => cases.flatMap((row) => (resultsById[row.id] ? [resultsById[row.id]] : [])),
    [cases, resultsById],
  );
  const e2eCoverage = coverage && "by_scenario" in coverage ? coverage : null;
  const groundingCoverage = coverage && "by_verdict" in coverage ? coverage : null;
  const displayedCases = groundingCoverage
    ? cases.filter((row) =>
        (!verdictFilter || row.verdict === verdictFilter)
        && (!languageFilter || row.language === languageFilter)
        && (!judgementOnly || row.judgement_call))
    : selectedScenario
      ? cases.filter((row) => row.scenario === selectedScenario)
      : cases;
  const groundingResults = Object.values(groundingById);
  const resultCount = groundingCoverage ? groundingResults.length : results.length;
  const passedCount = groundingCoverage
    ? groundingResults.filter((result) => result.match).length
    : results.filter(casePassed).length;
  const missingSections = coverage?.corpus_staleness.checked ? coverage.corpus_staleness.missing_sections : [];
  const invalidPicker = mode !== "smoke" && mode !== "all" && !value.trim();

  // `key` names what the confirm click belongs to, so arming one button never
  // lets another run through unconfirmed.
  async function startRun(key: string, runSubset: EvalSubset, count: number) {
    if (!set || running) return;
    if (count > 20 && confirmArmed !== key) {
      setConfirmArmed(key);
      return;
    }
    setConfirmArmed(null);
    setError("");
    setOutcome(null);
    tallyRef.current = emptyTally;
    cancelledRef.current = false;
    setSummary(null);
    setGroundingSummary(null);
    setResultSource("live");
    setLastRunAt(null);
    setRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let failed = false;
    try {
      for await (const event of streamEvalRun(set, runSubset, controller.signal)) {
        if (event.type === "run_start") {
          tallyRef.current = withTotal(tallyRef.current, event.case_count);
          setProgress(`Starting ${event.case_count} cases`);
        }
        if (event.type === "case_start") {
          setProgress(`${event.index}/${event.total} · ${event.id}`);
          setActiveCaseId(event.id);
        }
        if (event.type === "case_result") {
          setActiveCaseId((current) => (current === event.id ? null : current));
          if (isGroundingResult(event)) {
            tallyRef.current = addResult(tallyRef.current, event.match);
            setGroundingById((current) => ({ ...current, [event.id]: event }));
          } else {
            tallyRef.current = addResult(tallyRef.current, casePassed(event));
            setResultsById((current) => ({ ...current, [event.id]: event }));
          }
        }
        if (event.type === "run_summary") {
          if (isGroundingSummary(event)) setGroundingSummary(event);
          else setSummary(event);
        }
        if (event.type === "error") {
          failed = true;
          setOutcome(toOutcome("error", tallyRef.current, event.message));
        }
      }
      setLastRunAt(new Date().toISOString());
      // cancelRun owns the banner when it ended the stream.
      if (!failed && !cancelledRef.current && !controller.signal.aborted) {
        setOutcome(toOutcome("complete", tallyRef.current));
      }
    } catch (cause) {
      if (!controller.signal.aborted) {
        const message = cause instanceof EvalApiError && cause.status === 422
          ? `${cause.message}. Reseed the dedicated eval corpus before running.`
          : cause instanceof Error ? cause.message : "Eval run failed";
        setOutcome(toOutcome("error", tallyRef.current, message));
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setRunning(false);
      setProgress("");
      setActiveCaseId(null);
    }
  }

  const runIds = (ids: string[]) =>
    startRun(`ids:${ids.join(",")}`, { case_ids: ids.join(",") }, ids.length);

  function toggleSelected(id: string) {
    setConfirmArmed(null);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  function viewResults() {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById("eval-results")?.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }

  async function cancelRun() {
    cancelledRef.current = true;
    setOutcome(toOutcome("cancelled", tallyRef.current));
    await cancelEvalRun().catch(() => undefined);
    abortRef.current?.abort();
    setRunning(false);
    setProgress("");
    setActiveCaseId(null);
  }

  if (!coverage || !set) {
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
          <span className="rounded-full px-4 py-2 font-mono text-xs font-bold" style={{ background: palette.panel }}>n {resultCount || "—"}</span>
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
              {groundingCoverage
                ? `${coverage.total_cases} labelled claims · ${groundingCoverage.judgement_calls} judgement calls`
                : `${coverage.total_cases} benchmark cases · ${Object.keys(e2eCoverage!.by_scenario).length} scenarios`}
              {lastRunAt ? ` · results ${resultSource === "cached" ? "saved" : "completed"} ${new Date(lastRunAt).toLocaleString()}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={cancelRun}
              disabled={!running}
              className="inline-flex items-center gap-2 rounded-xl px-5 py-3 font-semibold disabled:opacity-45"
              style={{ background: palette.idle }}
            >
              <Stop />
              Cancel
            </button>
            <button
              type="button"
              onClick={() => startRun("picker", subset, estimatedCount)}
              disabled={running || invalidPicker || missingSections.length > 0}
              className="inline-flex min-w-[160px] items-center justify-center gap-2 rounded-xl px-5 py-3 font-semibold disabled:opacity-45"
              style={{ background: palette.accent, color: palette.panel }}
            >
              {running ? <Spinner /> : <Play />}
              {running ? `Running ${progress || "…"}` : confirmArmed === "picker" ? "Confirm run" : `Run ${estimatedCount || ""} ${groundingCoverage ? "claims" : "cases"}`}
            </button>
          </div>
        </header>

        {outcome && (
          <div
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3 text-sm"
            style={{
              borderColor: outcome.kind === "error" ? palette.warning : palette.line,
              background: outcome.kind === "complete" ? palette.passSoft : outcome.kind === "error" ? palette.failSoft : palette.panelSoft,
            }}
            role={outcome.kind === "error" ? "alert" : "status"}
          >
            <span className="font-semibold">{outcomeText(outcome)}</span>
            <div className="flex items-center gap-2">
              {outcome.kind === "complete" && (
                <button type="button" onClick={viewResults} className="rounded-lg px-3 py-1.5 font-semibold" style={{ background: palette.accent, color: palette.panel }}>
                  View results
                </button>
              )}
              <button type="button" onClick={() => setOutcome(null)} className="rounded-lg px-3 py-1.5 font-semibold" style={{ background: palette.idle }}>
                Dismiss
              </button>
            </div>
          </div>
        )}

        <section className="rounded-xl border p-3" style={{ borderColor: palette.line, background: palette.panelSoft }} aria-label="Run configuration">
          <div className="grid gap-3 md:grid-cols-[180px_220px_minmax(220px,1fr)_auto] md:items-center">
            <label className="flex items-center gap-3">
              <span className="font-mono text-[10px] font-bold uppercase tracking-[0.1em]" style={{ color: palette.muted }}>Set</span>
              <Select
                aria-label="Set"
                bold
                value={set}
                disabled={running}
                options={sets.map((name) => ({ value: name, label: formatScenario(name) }))}
                onChange={(next) => {
                  setCoverage(null);
                  setSelectedScenario(null);
                  setSelectedIds(new Set());
                  setVerdictFilter("");
                  setLanguageFilter("");
                  setJudgementOnly(false);
                  setError("");
                  setOutcome(null);
                  setMode("smoke");
                  setValue("");
                  setConfirmArmed(null);
                  setSet(next);
                }}
              />
            </label>
            <label className="flex items-center gap-3">
              <span className="font-mono text-[10px] font-bold uppercase tracking-[0.1em]" style={{ color: palette.muted }}>Run</span>
              <Select
                aria-label="Run"
                bold
                value={mode}
                disabled={running}
                options={groundingCoverage ? [{ value: "all", label: "All claims" }] : RUN_MODES}
                onChange={(next) => { setMode(next as PickerMode); setValue(""); setConfirmArmed(null); }}
              />
            </label>

            <div>
              {mode === "language" && (
                <Select aria-label="Language" value={value} onChange={setValue} options={[{ value: "", label: "Choose language…" }, { value: BILINGUAL_SUBSET, label: "bm + mixed (bilingual baseline)" }, ...Object.keys(e2eCoverage?.by_language ?? {}).map(asOption)]} />
              )}
              {mode === "category" && (
                <Select aria-label="Category" value={value} onChange={setValue} options={[{ value: "", label: "Choose category…" }, ...Object.keys(e2eCoverage?.by_category ?? {}).map(asOption)]} />
              )}
              {mode === "scenario" && (
                <Select aria-label="Scenario" value={value} onChange={setValue} options={[{ value: "", label: "Choose scenario…" }, ...Object.keys(e2eCoverage?.by_scenario ?? {}).map(asOption)]} />
              )}
              {mode === "case_id" && (
                <input value={value} onChange={(event) => setValue(event.target.value)} placeholder="evidence-90a-1" className="w-full rounded-xl border px-3 py-2.5 text-sm" style={{ borderColor: palette.line, background: palette.panel }} />
              )}
              {(mode === "smoke" || mode === "all") && (
                <p className="text-sm" style={{ color: palette.muted }}>
                  {groundingCoverage
                    ? "Runs the live grounding judge on every claim. Filter the list below to run a subset."
                    : mode === "smoke" ? "Fast signal across the CI-tagged cases." : "Complete benchmark; uses real model and judge tokens."}
                </p>
              )}
            </div>
            <div className="font-mono text-xs" style={{ color: palette.muted }}>{estimatedCount} selected</div>
          </div>
        </section>

        {confirmArmed && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.warningSoft }}>
            {(() => {
              const count = confirmArmed === "picker" ? estimatedCount : confirmArmed.slice(4).split(",").length;
              return groundingCoverage
                ? `${count} claims each call Jev, then the live grounding judge unless Jev clears the claim. The full set of ${coverage.total_cases} is up to ${coverage.total_cases} judge calls and incurs token cost.`
                : `${count} cases run the live agent and LLM judge, take roughly 5–8 minutes, and incur token cost.`;
            })()} Click <strong>Confirm run</strong> to continue.
          </div>
        )}

        {missingSections.length > 0 && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.failSoft }}>
            <strong>Run blocked:</strong> the eval corpus is missing {missingSections.length} required sections. Reseed the dedicated eval database first.
          </div>
        )}
        {!corpusChecked && !groundingCoverage && (
          <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.line, background: palette.panelSoft, color: palette.muted }}>
            Corpus status is not checked: {coverage.corpus_staleness.reason}. Coverage and saved results still work; a live run requires the eval database.
          </div>
        )}
        {error && <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: palette.warning, background: palette.failSoft }} role="alert">{error}</div>}

        {groundingCoverage && (
          <section id="eval-results" className="scroll-mt-4" aria-labelledby="matrix-title">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>Label vs judge</p>
                <h2 id="matrix-title" className="mt-1 text-2xl font-black">Where the judge disagrees</h2>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs" style={{ color: palette.muted }}>
                <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: palette.pass }} />match</span>
                <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ERROR_KIND_STYLE.too_lenient.fill }} />judge too lenient</span>
                <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ERROR_KIND_STYLE.too_strict.fill }} />judge too strict</span>
                {groundingSummary && (
                  <span className="font-mono font-bold" style={{ color: palette.ink }}>
                    {groundingSummary.matched}/{groundingSummary.total_cases - groundingSummary.judge_errors} matched
                    {" · "}{groundingSummary.by_error_kind.too_lenient ?? 0} lenient · {groundingSummary.by_error_kind.too_strict ?? 0} strict
                    {groundingSummary.judge_errors ? ` · ${groundingSummary.judge_errors} judge errors` : ""}
                  </span>
                )}
                {!groundingSummary && groundingResults.length > 0 && (
                  <span className="font-mono font-bold" style={{ color: palette.ink }}>{passedCount}/{groundingResults.length} matched</span>
                )}
              </div>
            </div>
            <GroundingMatrix rows={cases} results={groundingById} />
            <p className="mt-3 text-xs" style={{ color: palette.muted }}>A claim Jev clears counts as judge-supported, the same as in production.</p>
          </section>
        )}

        {e2eCoverage && <section id="eval-results" className="scroll-mt-4" aria-label="Result matrix: pass rate by scenario">
          <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" style={{ color: palette.muted }}>
            <span><b className="mr-1">✓</b> passed both gates</span>
            <span><b className="mr-1">×</b> failed L1 or judge</span>
            {summary && <span className="font-mono font-bold" style={{ color: palette.ink }}>{passedCount}/{results.length} overall</span>}
            <span className="ml-auto">Click a scenario cell to inspect only its cases below.</span>
          </div>
          <ResultMatrix
            coverage={e2eCoverage}
            cases={cases}
            resultsById={resultsById}
            source={resultSource}
            running={running}
            activeCaseId={activeCaseId}
            selectedScenario={selectedScenario}
            onSelectScenario={(scenario) => setSelectedScenario((current) => current === scenario ? null : scenario)}
          />
        </section>}

        <section className="grid gap-4 md:grid-cols-3" aria-label="How to use this dashboard">
          {(groundingCoverage ? [
            ["01", "Filter the claims", "Narrow the list by dataset label, language or judgement call. Counts beside each option come from the dataset."],
            ["02", "Run what you see", "Select the shown claims, or tick a few, then run them. Each row also has its own Run button."],
            ["03", "Read the mismatches", "Expand a claim to compare the dataset label with the judge label, the Jev score, and the judge's quote and reason."],
          ] : [
            ["01", "Choose a subset", "Start with Smoke for a quick signal. Use All only when you want the full benchmark."],
            ["02", "Run and watch", "Each completed case adds a ✓ or × to its scenario cell while the run is live."],
            ["03", "Inspect failures", "Select a colored cell, then expand a failed case in the list to see whether L1 or the judge rejected it."],
          ]).map(([number, title, copy]) => (
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
              <p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em]" style={{ color: palette.muted }}>Case browser</p>
              <h2 id="details-title" className="mt-1 text-2xl font-black">
                {selectedScenario ? `${formatScenario(selectedScenario)} cases` : groundingCoverage ? `${displayedCases.length} of ${cases.length} claims` : "All cases"}
              </h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {groundingCoverage && (
                <>
                  <Select
                    variant="pill"
                    aria-label="Filter by dataset label"
                    value={verdictFilter}
                    onChange={setVerdictFilter}
                    options={[{ value: "", label: "All labels" }, ...GROUNDING_LABELS.map((label) => ({ value: label, label: `${label} (${groundingCoverage.by_verdict[label] ?? 0})` }))]}
                  />
                  <Select
                    variant="pill"
                    aria-label="Filter by language"
                    value={languageFilter}
                    onChange={setLanguageFilter}
                    options={[{ value: "", label: "All languages" }, ...Object.entries(groundingCoverage.by_language).map(([language, count]) => ({ value: language, label: `${language} (${count})` }))]}
                  />
                  <label className="flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold" style={{ background: palette.panel }}>
                    <input type="checkbox" checked={judgementOnly} onChange={(event) => setJudgementOnly(event.target.checked)} />
                    Judgement calls only ({groundingCoverage.judgement_calls})
                  </label>
                  <button
                    type="button"
                    onClick={() => { setConfirmArmed(null); setSelectedIds(new Set(displayedCases.map((row) => row.id))); }}
                    disabled={displayedCases.length === 0}
                    className="rounded-full px-4 py-2 text-xs font-semibold disabled:opacity-45"
                    style={{ background: palette.panel }}
                  >
                    Select {displayedCases.length} shown
                  </button>
                </>
              )}
              {selectedIds.size > 0 && (
                <>
                  <button
                    type="button"
                    onClick={() => runIds(cases.filter((row) => selectedIds.has(row.id)).map((row) => row.id))}
                    disabled={running}
                    className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-xs font-semibold disabled:opacity-45"
                    style={{ background: palette.accent, color: palette.panel }}
                  >
                    <Play />
                    {confirmArmed?.startsWith("ids:") && selectedIds.size > 20 ? "Confirm run" : `Run ${selectedIds.size} selected`}
                  </button>
                  <button type="button" onClick={() => { setSelectedIds(new Set()); setConfirmArmed(null); }} className="rounded-full px-4 py-2 text-xs font-semibold" style={{ background: palette.panel }}>Clear selection</button>
                </>
              )}
            {selectedScenario && (
              <button type="button" onClick={() => setSelectedScenario(null)} className="rounded-full px-4 py-2 text-xs font-semibold" style={{ background: palette.panel }}>Show all cases</button>
            )}
            </div>
          </div>
          <div className="space-y-2">
            {displayedCases.map((row) => (
              <div key={row.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2">
                <input
                  type="checkbox"
                  aria-label={`Select ${row.id}`}
                  checked={selectedIds.has(row.id)}
                  onChange={() => toggleSelected(row.id)}
                  className="mt-4 h-4 w-4"
                />
                <CaseRowDetail row={row} result={resultsById[row.id]} grounding={groundingById[row.id]} active={row.id === activeCaseId} />
                <button
                  type="button"
                  onClick={() => runIds([row.id])}
                  disabled={running || missingSections.length > 0}
                  className="mt-2.5 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.08em] disabled:opacity-45"
                  style={{ background: palette.panel, border: `1px solid ${palette.line}` }}
                >
                  <Play />
                  Run
                </button>
              </div>
            ))}
            {displayedCases.length === 0 && (
              <div className="rounded-xl border border-dashed p-6 text-center text-sm" style={{ borderColor: palette.line, color: palette.muted }}>
                This set has no cases.
              </div>
            )}
          </div>
        </section>

        {e2eCoverage && <details className="rounded-xl border" style={{ borderColor: palette.line, background: palette.panelSoft }}>
          <summary className="cursor-pointer px-4 py-3 font-semibold">
            Dataset coverage and gaps
            <span className="mt-0.5 block text-xs font-normal" style={{ color: palette.muted }}>Dataset health, independent of any run: case counts and where the dataset is thin.</span>
          </summary>
          <div className="grid gap-4 border-t px-4 py-4 lg:grid-cols-[1fr_1.4fr]" style={{ borderColor: palette.line }}>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              {[
                ["Total", coverage.total_cases],
                ["Smoke", e2eCoverage.smoke_cases],
                ["Allow", e2eCoverage.by_policy.allow ?? 0],
                ["Block", e2eCoverage.by_policy.block ?? 0],
              ].map(([label, count]) => (
                <div key={label} className="rounded-xl p-4" style={{ background: palette.panel }}>
                  <div className="font-mono text-[10px] uppercase" style={{ color: palette.muted }}>{label}</div>
                  <div className="mt-1 text-2xl font-black">{count}</div>
                </div>
              ))}
            </div>
            <div className="space-y-2">
              {e2eCoverage.gap_flags.map((flag, index) => (
                <div key={`${flag.rule}-${flag.scenario ?? flag.category ?? index}`} className="rounded-xl px-4 py-3 text-sm" style={{ background: palette.warningSoft }}>{flagText(flag)}</div>
              ))}
            </div>
          </div>
        </details>}
      </div>
    </main>
  );
}
