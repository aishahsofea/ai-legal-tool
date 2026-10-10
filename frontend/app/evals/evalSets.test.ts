import { describe, expect, it } from "vitest";
import type { RoutingCoverage } from "@/lib/evalsTransport";
import { defaultMode, modesFor, routingEstimate, setKindOf } from "./evalSets";

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
