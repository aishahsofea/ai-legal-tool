import type { CoverageResponse, GroundingCoverage, RoutingCoverage } from "@/lib/evalsTransport";

export type SetKind = "end_to_end" | "grounding" | "routing";
export type PickerMode = "smoke" | "all" | "language" | "category" | "scenario" | "case_id" | "query_type" | "case_ids";

type Coverage = CoverageResponse | GroundingCoverage | RoutingCoverage;

// Each set's coverage payload has one key the others lack.
export function setKindOf(coverage: Coverage): SetKind {
  if ("by_verdict" in coverage) return "grounding";
  if ("by_scenario" in coverage) return "end_to_end";
  return "routing";
}

type ModeOption = { value: PickerMode; label: string };

const END_TO_END_MODES: ModeOption[] = [
  { value: "smoke", label: "Smoke subset" },
  { value: "all", label: "All cases" },
  { value: "language", label: "By language" },
  { value: "category", label: "By category" },
  { value: "scenario", label: "By scenario" },
  { value: "case_id", label: "Single case ID" },
];

// The routing runner has no smoke, category or scenario selection (#235).
const ROUTING_MODES: ModeOption[] = [
  { value: "all", label: "All cases" },
  { value: "language", label: "By language" },
  { value: "query_type", label: "By query type" },
  { value: "case_ids", label: "Case IDs" },
];

export function modesFor(kind: SetKind): ModeOption[] {
  if (kind === "grounding") return [{ value: "all", label: "All claims" }];
  return kind === "routing" ? ROUTING_MODES : END_TO_END_MODES;
}

export const defaultMode = (kind: SetKind): PickerMode => (kind === "end_to_end" ? "smoke" : "all");

export function routingEstimate(coverage: RoutingCoverage, mode: PickerMode, value: string): number {
  if (mode === "all") return coverage.total_cases;
  if (mode === "query_type") return coverage.by_query_type[value] ?? 0;
  const items = value.split(",").map((item) => item.trim()).filter(Boolean);
  if (mode === "language") return items.reduce((total, language) => total + (coverage.by_language[language] ?? 0), 0);
  return mode === "case_ids" ? items.length : 0;
}
