import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowMap } from "./WorkflowMap";

const mocks = vi.hoisted(() => ({
  fetchEvalWorkflow: vi.fn(),
  options: { current: undefined as { elements?: Array<{ data: Record<string, string>; position?: { x: number; y: number } }> } | undefined },
  select: vi.fn(),
  destroy: vi.fn(),
}));

vi.mock("@/lib/evalsTransport", async () => ({
  ...(await vi.importActual<typeof import("@/lib/evalsTransport")>("@/lib/evalsTransport")),
  fetchEvalWorkflow: mocks.fetchEvalWorkflow,
}));

vi.mock("cytoscape", () => ({
  default: vi.fn((options) => {
    mocks.options.current = options;
    return {
      destroy: mocks.destroy,
      on: vi.fn(),
      $: () => ({ unselect: vi.fn() }),
      $id: (id: string) => ({ select: () => mocks.select(id) }),
    };
  }),
}));

const node = (id: string, kind: string, rank: number, lane: number, evals: object[]) => ({
  id, kind, description: `${id} description`, reads: ["query"], writes: ["query_type"], rank, lane, evals,
});

beforeEach(() => {
  mocks.fetchEvalWorkflow.mockResolvedValue({
    nodes: [
      node("router", "llm", 1, 2, [{ set: "routing" }]),
      node("clarify", "control", 2, 1, []),
      node("recall", "deterministic", 3, 2, [{ script: "evals/semantic_memory.py" }]),
    ],
    edges: [
      { source: "router", target: "clarify", conditional: true, label: "clarify" },
      { source: "clarify", target: "router", conditional: false, label: null },
    ],
  });
});

describe("WorkflowMap", () => {
  it("draws nodes at rank/lane positions and edges with labels", async () => {
    render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    await waitFor(() => expect(mocks.options.current).toBeDefined());
    const els = mocks.options.current!.elements!;
    expect(els.find((e) => e.data.id === "router")?.position).toEqual({ x: 340, y: 80 });
    expect(els.find((e) => e.data.id === "router->clarify")?.data).toMatchObject({ label: "clarify", conditional: "yes" });
    expect(els.find((e) => e.data.id === "clarify->router")?.data).toMatchObject({ label: "", conditional: "no" });
  });

  it("opens the panel with the runnable set and selects it on the canvas", async () => {
    const onSelectSet = vi.fn();
    render(<WorkflowMap onSelectSet={onSelectSet} onRunSet={vi.fn()} running={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "router" }));
    expect(screen.getByText("router description")).toBeInTheDocument();
    await waitFor(() => expect(mocks.select).toHaveBeenCalledWith("router"));
    await userEvent.click(screen.getByRole("button", { name: "routing" }));
    expect(onSelectSet).toHaveBeenCalledWith("routing");
  });

  it("Run button asks the dashboard to run the set, and is disabled while a run is active", async () => {
    const onRunSet = vi.fn();
    const { rerender } = render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={onRunSet} running={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "router" }));
    await userEvent.click(screen.getByRole("button", { name: "Run routing" }));
    expect(onRunSet).toHaveBeenCalledWith("routing");
    rerender(<WorkflowMap onSelectSet={vi.fn()} onRunSet={onRunSet} running />);
    expect(screen.getByRole("button", { name: "Run routing" })).toBeDisabled();
  });

  it("says no eval yet for a node without evals", async () => {
    render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "clarify" }));
    expect(screen.getByText("No eval yet.")).toBeInTheDocument();
  });

  it("lists manual scripts as plain text", async () => {
    render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "recall" }));
    expect(screen.getByText("evals/semantic_memory.py")).toBeInTheDocument();
    expect(screen.getByText(/manual, not runnable/)).toBeInTheDocument();
  });

  it("opens the panel with the keyboard", async () => {
    render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    (await screen.findByRole("button", { name: "router" })).focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByText("router description")).toBeInTheDocument();
  });

  it("shows the error when the fetch fails", async () => {
    mocks.fetchEvalWorkflow.mockRejectedValue(new Error("boom"));
    render(<WorkflowMap onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});
