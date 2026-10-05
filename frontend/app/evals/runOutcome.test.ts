import { describe, expect, it } from "vitest";
import { addResult, emptyTally, outcomeText, toOutcome, withTotal } from "./runOutcome";

describe("run outcome", () => {
  it("tallies only the results of this run", () => {
    let tally = withTotal(emptyTally, 3);
    tally = addResult(tally, true);
    tally = addResult(tally, false);
    tally = addResult(tally, true);
    expect(tally).toEqual({ total: 3, completed: 3, passed: 2 });
  });

  it("does not mutate the previous tally", () => {
    const before = withTotal(emptyTally, 2);
    addResult(before, true);
    expect(before).toEqual({ total: 2, completed: 0, passed: 0 });
  });

  it("words each outcome", () => {
    const tally = addResult(withTotal(emptyTally, 5), true);
    expect(outcomeText(toOutcome("complete", tally))).toBe("Eval complete: 1/5 passed");
    expect(outcomeText(toOutcome("cancelled", tally))).toBe("Run cancelled after 1 of 5 cases.");
    expect(outcomeText(toOutcome("error", tally, "boom"))).toBe("boom");
    expect(outcomeText(toOutcome("error", tally))).toBe("Eval run failed");
  });
});
