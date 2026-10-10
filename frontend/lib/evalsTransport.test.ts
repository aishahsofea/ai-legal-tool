import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchEvalCases,
  fetchEvalCoverage,
  fetchEvalResults,
  fetchEvalSets,
  isGroundingResult,
  isGroundingSummary,
  isRoutingResult,
  isRoutingSummary,
  streamEvalRun,
} from "./evalsTransport";

function mockFetch(body: unknown, status = 200) {
  const fn = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("evalsTransport set routing", () => {
  it("fetchEvalSets reads the registry", async () => {
    mockFetch({ default: "end_to_end", sets: [{ name: "end_to_end" }] });
    expect((await fetchEvalSets()).sets).toEqual([{ name: "end_to_end" }]);
  });

  it("fetchEvalCases unwraps cases and passes the set", async () => {
    const fn = mockFetch({ set: "end_to_end", cases: [{ id: "a", status: "not run", result: null }] });
    const rows = await fetchEvalCases("end_to_end");
    expect(rows[0].id).toBe("a");
    expect(String(fn.mock.calls[0][0])).toContain("/evals/cases?set=end_to_end");
  });

  it("coverage and results carry the set; results 404 is null", async () => {
    const fn = mockFetch({});
    await fetchEvalCoverage("end_to_end");
    expect(String(fn.mock.calls[0][0])).toContain("/evals/coverage?set=end_to_end");
    mockFetch({ available: false }, 404);
    expect(await fetchEvalResults("end_to_end")).toBeNull();
  });

  it("streamEvalRun posts the set with the subset", async () => {
    const fn = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fn);
    for await (const _event of streamEvalRun("end_to_end", "smoke")) void _event;
    expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ set: "end_to_end", subset: "smoke" });
  });
});

describe("grounding payload guards", () => {
  it("tells a grounding result from an end-to-end one", () => {
    expect(isGroundingResult({ id: "g001", judge_label: "supported", match: true })).toBe(true);
    expect(isGroundingResult({ id: "a", judge: { passed: true }, l1_failures: [] })).toBe(false);
  });

  it("tells a grounding summary from an end-to-end one", () => {
    expect(isGroundingSummary({ matched: 3, match_rate: 0.5 })).toBe(true);
    expect(isGroundingSummary({ judge_passed: 3, judge_total: 4 })).toBe(false);
  });
});

describe("routing payload guards", () => {
  const routing = { id: "r001", label_type: "topical", query_type: "topical", type_match: true };
  const grounding = { id: "g001", judge_label: "supported", match: true };
  const endToEnd = { id: "a", judge: { passed: true }, l1_failures: [] };

  it("matches a routing result, including an errored row", () => {
    expect(isRoutingResult(routing)).toBe(true);
    expect(isRoutingResult({ id: "r002", label_type: "clarify", error: "Timeout" })).toBe(true);
  });

  it("does not match grounding or end-to-end results", () => {
    expect(isRoutingResult(grounding)).toBe(false);
    expect(isRoutingResult(endToEnd)).toBe(false);
  });

  it("matches a routing summary only", () => {
    expect(isRoutingSummary({ query_type_accuracy: 0.9, language_accuracy: 1 })).toBe(true);
    expect(isRoutingSummary({ matched: 3, match_rate: 0.5 })).toBe(false);
    expect(isRoutingSummary({ judge_passed: 3, judge_total: 4 })).toBe(false);
  });

  it("is not matched by the other guards", () => {
    expect(isGroundingResult(routing)).toBe(false);
    expect(isGroundingSummary({ query_type_accuracy: 0.9 })).toBe(false);
  });
});
