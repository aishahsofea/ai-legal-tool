import { describe, expect, it } from "vitest";
import type { RoutingCoverage } from "@/lib/evalsTransport";
import { costBasisOf, costText, defaultMode, modesFor, routingEstimate, setKindOf } from "./evalSets";

const routing: RoutingCoverage = {
  total_cases: 99,
  by_query_type: { topical: 30, clarify: 10 },
  by_language: { en: 60, bm: 25, mixed: 14 },
  corpus_staleness: { checked: false, reason: "n/a" },
};

describe("set kind", () => {
  it("tells the three coverage shapes apart", () => {
    expect(setKindOf(routing)).toBe("routing");
    expect(setKindOf({ by_verdict: {} } as never)).toBe("grounding");
    expect(setKindOf({ by_scenario: {} } as never)).toBe("end_to_end");
  });
});

describe("run modes per set", () => {
  it("offers routing only the modes its runner supports", () => {
    expect(modesFor("routing").map((mode) => mode.value)).toEqual(["all", "language", "query_type", "case_ids"]);
  });

  it("keeps the end-to-end and grounding lists", () => {
    expect(modesFor("end_to_end").map((mode) => mode.value)).toContain("smoke");
    expect(modesFor("grounding").map((mode) => mode.value)).toEqual(["all"]);
  });

  it("defaults to smoke only for end-to-end", () => {
    expect(defaultMode("end_to_end")).toBe("smoke");
    expect(defaultMode("routing")).toBe("all");
    expect(defaultMode("grounding")).toBe("all");
  });
});

describe("routingEstimate", () => {
  it("counts each mode from coverage", () => {
    expect(routingEstimate(routing, "all", "")).toBe(99);
    expect(routingEstimate(routing, "query_type", "topical")).toBe(30);
    expect(routingEstimate(routing, "language", "bm, mixed")).toBe(39);
    expect(routingEstimate(routing, "case_ids", "a, b,,c")).toBe(3);
  });
});

describe("cost estimate", () => {
  const report = (usage: object | undefined, cases: number) =>
    ({ generated_at: "", summary: { usage }, results: Array(cases).fill({}) }) as never;

  it("scales the last run's per-case cost to the selection", () => {
    const basis = costBasisOf(report({ total: { calls: 8, usd: 0.04 }, partial: false }, 4));
    expect(basis).toEqual({ perCase: 0.01, cases: 4, usd: 0.04, partial: false });
    expect(costText(basis, 30)).toBe("Estimated cost $0.30, from the last saved run ($0.04 for 4 cases).");
  });

  it("marks a partial price as a floor", () => {
    expect(costText(costBasisOf(report({ total: { calls: 1, usd: 0.001 }, partial: true }, 1)), 2)).toMatch(/at least \$0\.0020/);
  });

  it("has no basis without recorded usage", () => {
    expect(costBasisOf(null)).toBeNull();
    expect(costBasisOf(report(undefined, 3))).toBeNull();
    expect(costText(null, 5)).toMatch(/no saved run/);
  });
});
