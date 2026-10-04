import { parseSseStream } from "@/lib/queryTransport";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type EvalSubset =
  | "smoke"
  | "all"
  // Comma-separated, e.g. "bm,mixed": the bilingual baseline is one subset.
  | { language: string }
  | { category: string }
  | { scenario: string }
  | { case_id: string }
  // Comma-separated ids from the case list's row selection.
  | { case_ids: string };

export type GroundingLabel = "supported" | "partial" | "unsupported";

export interface GapFlag {
  rule: "thin_scenario" | "weak_boundary_coverage" | "no_smoke_coverage";
  scenario?: string;
  category?: string;
  count?: number;
  threshold?: number;
  block_pct?: number;
}

export interface MissingSection {
  act_number: string;
  section_number: string;
}

export interface CoverageResponse {
  total_cases: number;
  smoke_cases: number;
  by_policy: Record<string, number>;
  by_category: Record<string, number>;
  by_scenario: Record<string, number>;
  by_language: Record<string, number>;
  gap_flags: GapFlag[];
  corpus_staleness:
    | { checked: true; missing_sections: MissingSection[] }
    | { checked: false; reason: string };
}

// Counts for the grounding set, which has no scenarios, policies or gap flags.
export interface GroundingCoverage {
  total_cases: number;
  by_verdict: Record<string, number>;
  by_language: Record<string, number>;
  judgement_calls: number;
  corpus_staleness: { checked: false; reason: string };
}

export interface EvalCitation {
  act_number: string;
  act_title?: string;
  section_number: string;
  pdf_url?: string;
  page_number?: number | null;
}

export interface SectionRecall {
  expected: number;
  matched: number;
  recall: number;
  matched_sections: MissingSection[];
  missing_sections: MissingSection[];
}

export interface EvalCaseResult {
  id: string;
  category: string;
  scenario: string;
  expected_policy: string;
  expected_act_number?: string | null;
  expected_section?: string | null;
  section_recall?: SectionRecall | null;
  l1_failures: string[];
  l1_failure_details?: Record<string, string>;
  judge: { passed: boolean; reasoning?: string; [key: string]: unknown } | null;
  query: string;
  response: string;
  citations: EvalCitation[];
  elapsed_seconds: number;
}

export interface ScenarioStats {
  passed: number;
  total: number;
  rate: number;
}

export interface EvalRunSummary {
  l1: Record<string, unknown>;
  section_recall_mean?: number | null;
  section_recall_cases?: number;
  judge_passed: number;
  judge_total: number;
  by_scenario: Record<string, ScenarioStats>;
}

export interface GroundingCase {
  id: string;
  language: string;
  claim: string;
  act_number: string;
  act_title: string;
  section_number: string;
  source_text: string;
  verdict: GroundingLabel;
  judgement_call?: boolean;
  note?: string;
}

// `too_lenient`: the judge cleared a claim the dataset marks weaker.
// `too_strict`: the judge flagged a claim the dataset marks stronger.
export type GroundingErrorKind = "too_lenient" | "too_strict";

export interface GroundingResult {
  id: string;
  case: GroundingCase;
  label: GroundingLabel;
  judge_label: GroundingLabel | null;
  match: boolean;
  error_kind: GroundingErrorKind | null;
  jev_score: number | null;
  jev_cleared: boolean;
  jev_error: boolean;
  reason: string;
  quote: string;
  // Set when the judge call failed; there is no label to compare.
  error?: string;
}

export interface GroundingSummary {
  total_cases: number;
  judge_errors: number;
  matched: number;
  match_rate: number;
  by_error_kind: Partial<Record<GroundingErrorKind, number>>;
  jev_cleared: number;
  jev_errors: number;
}

export function isGroundingResult(value: object): value is GroundingResult {
  return "judge_label" in value;
}

export function isGroundingSummary(value: object): value is GroundingSummary {
  return "match_rate" in value;
}

export type EvalEvent =
  | { type: "run_start"; subset: EvalSubset; case_count: number }
  | { type: "case_start"; id: string; index: number; total: number }
  | ({ type: "case_result" } & (EvalCaseResult | GroundingResult))
  | ({ type: "run_summary" } & (EvalRunSummary | GroundingSummary))
  | { type: "error"; message: string }
  | { type: "done" };

export interface PersistedResult {
  case: {
    id: string;
    category: string;
    scenario: string;
    query: string;
    expected_policy?: string;
    expected_act_number?: string | null;
    expected_section?: string | null;
  };
  agent: { final_response?: string; citations?: EvalCitation[] };
  section_recall?: SectionRecall | null;
  l1_failures?: Record<string, string>;
  judge: EvalCaseResult["judge"];
}

export interface EvalResultsReport {
  generated_at: string;
  summary: (EvalRunSummary & { total_cases: number }) | GroundingSummary;
  results: (PersistedResult | GroundingResult)[];
}

export interface EvalSetInfo {
  name: string;
}

export interface EvalSetsResponse {
  default: string;
  sets: EvalSetInfo[];
}

export type EvalCaseStatus = "passed" | "failed" | "not run";

// One dataset case merged with its latest saved result, as GET /evals/cases returns it.
// End-to-end rows carry `query`/`scenario`; grounding rows carry `claim`/`verdict`.
export interface EvalCaseRow extends Partial<GroundingCase> {
  id: string;
  category?: string;
  scenario?: string;
  query?: string;
  expected_policy?: string;
  expected_act_number?: string | null;
  expected_section?: string | null;
  status: EvalCaseStatus;
  result: PersistedResult | GroundingResult | null;
}

export class EvalApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
  }
}

async function responseError(response: Response): Promise<EvalApiError> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    detail = undefined;
  }
  const message = typeof detail === "string"
    ? detail
    : (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string")
      ? detail.message
      : `HTTP ${response.status}`;
  return new EvalApiError(message, response.status, detail);
}

function setQuery(set: string) {
  return `set=${encodeURIComponent(set)}`;
}

export async function fetchEvalSets(): Promise<EvalSetsResponse> {
  const response = await fetch(`${API_URL}/evals/sets`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

export async function fetchEvalCases(set: string): Promise<EvalCaseRow[]> {
  const response = await fetch(`${API_URL}/evals/cases?${setQuery(set)}`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response);
  return (await response.json()).cases;
}

export async function fetchEvalCoverage(set: string): Promise<CoverageResponse | GroundingCoverage> {
  const response = await fetch(`${API_URL}/evals/coverage?${setQuery(set)}`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

export async function fetchEvalResults(set: string): Promise<EvalResultsReport | null> {
  const response = await fetch(`${API_URL}/evals/results?${setQuery(set)}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw await responseError(response);
  return response.json();
}

function decodeEvalEvent(raw: string): EvalEvent | null {
  if (!raw) return null;
  try {
    const event = JSON.parse(raw) as EvalEvent;
    return typeof event.type === "string" ? event : null;
  } catch {
    return null;
  }
}

export async function* streamEvalRun(
  set: string,
  subset: EvalSubset,
  signal?: AbortSignal,
): AsyncGenerator<EvalEvent> {
  const response = await fetch(`${API_URL}/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ set, subset }),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new Error("No response body");
  yield* parseSseStream(response.body, decodeEvalEvent, signal);
}

export async function cancelEvalRun(): Promise<void> {
  await fetch(`${API_URL}/evals/cancel`, { method: "POST", keepalive: true });
}

export function flattenPersistedResult(result: PersistedResult): EvalCaseResult {
  return {
    id: result.case.id,
    category: result.case.category,
    scenario: result.case.scenario,
    expected_policy: result.case.expected_policy ?? "allow",
    expected_act_number: result.case.expected_act_number,
    expected_section: result.case.expected_section,
    section_recall: result.section_recall ?? null,
    l1_failures: Object.keys(result.l1_failures ?? {}),
    l1_failure_details: result.l1_failures ?? {},
    judge: result.judge,
    query: result.case.query,
    response: result.agent.final_response ?? "",
    citations: result.agent.citations ?? [],
    elapsed_seconds: 0,
  };
}
