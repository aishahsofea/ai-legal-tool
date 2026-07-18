import { parseSseStream } from "@/lib/queryTransport";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type EvalSubset =
  | "smoke"
  | "all"
  | { category: string }
  | { scenario: string }
  | { case_id: string };

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
  gap_flags: GapFlag[];
  corpus_staleness:
    | { checked: true; missing_sections: MissingSection[] }
    | { checked: false; reason: string };
}

export interface EvalCitation {
  act_number: string;
  act_title?: string;
  section_number: string;
  pdf_url?: string;
  page_number?: number | null;
}

export interface EvalCaseResult {
  id: string;
  category: string;
  scenario: string;
  expected_policy: string;
  expected_act_number?: string | null;
  expected_section?: string | null;
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
  judge_passed: number;
  judge_total: number;
  by_scenario: Record<string, ScenarioStats>;
}

export type EvalEvent =
  | { type: "run_start"; subset: EvalSubset; case_count: number }
  | { type: "case_start"; id: string; index: number; total: number }
  | ({ type: "case_result" } & EvalCaseResult)
  | ({ type: "run_summary" } & EvalRunSummary)
  | { type: "error"; message: string }
  | { type: "done" };

interface PersistedResult {
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
  l1_failures?: Record<string, string>;
  judge: EvalCaseResult["judge"];
}

export interface EvalResultsReport {
  generated_at: string;
  summary: EvalRunSummary & { total_cases: number };
  results: PersistedResult[];
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

export async function fetchEvalCoverage(): Promise<CoverageResponse> {
  const response = await fetch(`${API_URL}/evals/coverage`, { cache: "no-store" });
  if (!response.ok) throw await responseError(response);
  return response.json();
}

export async function fetchEvalResults(): Promise<EvalResultsReport | null> {
  const response = await fetch(`${API_URL}/evals/results`, { cache: "no-store" });
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
  subset: EvalSubset,
  signal?: AbortSignal,
): AsyncGenerator<EvalEvent> {
  const response = await fetch(`${API_URL}/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subset }),
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
    l1_failures: Object.keys(result.l1_failures ?? {}),
    l1_failure_details: result.l1_failures ?? {},
    judge: result.judge,
    query: result.case.query,
    response: result.agent.final_response ?? "",
    citations: result.agent.citations ?? [],
    elapsed_seconds: 0,
  };
}
