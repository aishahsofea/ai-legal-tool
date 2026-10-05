export interface RunTally {
  total: number;
  completed: number;
  passed: number;
}

export interface RunOutcome extends RunTally {
  kind: "complete" | "cancelled" | "error";
  message?: string;
}

export const emptyTally: RunTally = { total: 0, completed: 0, passed: 0 };

export const withTotal = (tally: RunTally, total: number): RunTally => ({ ...tally, total });

export const addResult = (tally: RunTally, passed: boolean): RunTally => ({
  ...tally,
  completed: tally.completed + 1,
  passed: tally.passed + (passed ? 1 : 0),
});

export const toOutcome = (kind: RunOutcome["kind"], tally: RunTally, message?: string): RunOutcome => ({
  kind,
  ...tally,
  message,
});

export function outcomeText(outcome: RunOutcome) {
  if (outcome.kind === "complete") return `Eval complete: ${outcome.passed}/${outcome.total} passed`;
  if (outcome.kind === "cancelled") return `Run cancelled after ${outcome.completed} of ${outcome.total} cases.`;
  return outcome.message || "Eval run failed";
}
