import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvalDashboard from "./EvalDashboard";

const mocks = vi.hoisted(() => ({
  streamEvalRun: vi.fn(),
}));

vi.mock("./WorkflowMap", () => ({
  WorkflowMap: ({ onRunSet }: { onRunSet: (name: string) => void }) => (
    <button type="button" onClick={() => onRunSet("routing")}>map run routing</button>
  ),
}));

vi.mock("@/lib/evalsTransport", async () => ({
  ...(await vi.importActual<typeof import("@/lib/evalsTransport")>("@/lib/evalsTransport")),
  fetchEvalSets: vi.fn().mockResolvedValue({ default: "end_to_end", sets: [{ name: "end_to_end" }, { name: "routing" }] }),
  fetchEvalCases: vi.fn().mockResolvedValue([]),
  fetchEvalResults: vi.fn().mockResolvedValue(null),
  fetchEvalCoverage: vi.fn(async (set: string) =>
    set === "routing"
      ? { total_cases: 3, by_query_type: {}, by_language: {}, corpus_staleness: { checked: false, reason: "n/a" } }
      : { total_cases: 30, smoke_cases: 5, by_policy: {}, by_category: {}, by_scenario: {}, by_language: {}, gap_flags: [], corpus_staleness: { checked: false, reason: "n/a" } }),
  streamEvalRun: mocks.streamEvalRun,
}));

beforeEach(() => {
  mocks.streamEvalRun.mockReset();
  mocks.streamEvalRun.mockImplementation(async function* () {});
});

describe("EvalDashboard run confirm", () => {
  it("confirms a node run even under 20 cases, then runs the set's default subset", async () => {
    render(<EvalDashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "map run routing" }));
    expect(await screen.findByText(/3 queries each call the live router/)).toBeInTheDocument();
    expect(mocks.streamEvalRun).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(mocks.streamEvalRun).toHaveBeenCalledTimes(1));
    expect(mocks.streamEvalRun.mock.calls[0].slice(0, 2)).toEqual(["routing", "all"]);
  });

  it("dismiss disarms the confirm without a run", async () => {
    render(<EvalDashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "map run routing" }));
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/Click/)).not.toBeInTheDocument();
    expect(mocks.streamEvalRun).not.toHaveBeenCalled();
  });

  it("picker still runs under 20 cases without a confirm", async () => {
    render(<EvalDashboard />);
    await userEvent.click(await screen.findByRole("button", { name: "Run 5 cases" }));
    await waitFor(() => expect(mocks.streamEvalRun).toHaveBeenCalledTimes(1));
    expect(mocks.streamEvalRun.mock.calls[0].slice(0, 2)).toEqual(["end_to_end", "smoke"]);
  });
});
