import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { bendThrough, edgeBend, nodeLabel, WorkflowMap } from "./WorkflowMap";

type Element = { data: Record<string, string | number>; position?: { x: number; y: number }; classes?: string };

const mocks = vi.hoisted(() => ({
  fetchEvalWorkflow: vi.fn(),
  options: { current: undefined as { elements?: Element[] } | undefined },
  tap: { current: undefined as ((event: { target: { id: () => string } }) => void) | undefined },
  select: vi.fn(),
  toggleNodeClass: vi.fn(),
  toggleEdgeClass: vi.fn(),
  zoom: vi.fn(),
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
      on: (event: string, ...rest: unknown[]) => {
        if (event === "tap") mocks.tap.current = rest[1] as typeof mocks.tap.current;
      },
      $: () => ({ unselect: vi.fn() }),
      $id: (id: string) => ({
        select: () => mocks.select(id),
        toggleClass: (name: string, on: boolean) => mocks.toggleNodeClass(id, name, on),
        position: vi.fn(),
      }),
      edges: () => ({ toggleClass: mocks.toggleEdgeClass }),
      zoom: (arg?: { level: number }) => (arg ? mocks.zoom(arg.level) : 1),
      width: () => 800,
      height: () => 600,
      fit: vi.fn(),
    };
  }),
}));

const node = (id: string, kind: string, rank: number, lane: number, evals: object[], models: string[] = []) => ({
  id, kind, description: `${id} description`, reads: ["query"], writes: ["query_type"], rank, lane, models, evals,
});

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
  vi.clearAllMocks();
  mocks.options.current = undefined;
  mocks.tap.current = undefined;
  mocks.fetchEvalWorkflow.mockResolvedValue({
    nodes: [
      node("router", "llm", 1, 2, [{ set: "routing" }], ["jev-1.13.0", "nvidia/Nemotron-3_5-Lightning"]),
      node("clarify", "control", 2, 1, []),
      node("recall", "deterministic", 3, 2, [{ script: "evals/semantic_memory.py" }]),
      node("record_turn", "control", 6, 1, []),
    ],
    edges: [
      { source: "router", target: "clarify", conditional: true, label: "clarify" },
      { source: "clarify", target: "router", conditional: false, label: null },
      { source: "recall", target: "record_turn", conditional: false, label: null },
    ],
  });
});

async function renderMap(props: Partial<Parameters<typeof WorkflowMap>[0]> = {}) {
  const view = render(<WorkflowMap activeSet={null} onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} {...props} />);
  await waitFor(() => expect(mocks.tap.current).toBeDefined());
  return view;
}

const tap = (id: string) => act(() => mocks.tap.current!({ target: { id: () => id } }));

describe("WorkflowMap", () => {
  it("draws nodes at rank/lane positions with the model under the id", async () => {
    await renderMap();
    const els = mocks.options.current!.elements!;
    expect(els.find((e) => e.data.id === "router")).toMatchObject({ position: { x: 380, y: 72 }, data: { label: "router\njev-1.13.0\n→ Nemotron-3_5-Lightning", height: 51 } });
    expect(els.find((e) => e.data.id === "clarify")?.data.label).toBe("clarify");
    expect(els.find((e) => e.data.id === "router->clarify")?.data).toMatchObject({ label: "clarify", conditional: "yes" });
  });

  it("curves every cross-lane edge, so a router branch and its return edge bow apart", async () => {
    await renderMap();
    const els = mocks.options.current!.elements!;
    const out = els.find((e) => e.data.id === "router->clarify")!.data;
    const back = els.find((e) => e.data.id === "clarify->router")!.data;
    expect(out.bendDistance).not.toBe(0);
    expect(back.bendDistance).toBe(out.bendDistance);
  });

  it("clicking a node opens its panel and selects its eval set", async () => {
    const onSelectSet = vi.fn();
    await renderMap({ onSelectSet });
    await tap("router");
    expect(screen.getByText("router description")).toBeInTheDocument();
    expect(screen.getByText("jev-1.13.0 → nvidia/Nemotron-3_5-Lightning")).toBeInTheDocument();
    expect(screen.getByText("Models, in call order")).toBeInTheDocument();
    expect(onSelectSet).toHaveBeenCalledWith("routing");
    await waitFor(() => expect(mocks.select).toHaveBeenCalledWith("router"));
  });

  it("clicking a node without a runnable set leaves the set alone", async () => {
    const onSelectSet = vi.fn();
    await renderMap({ onSelectSet });
    await tap("clarify");
    expect(screen.getByText("No eval yet.")).toBeInTheDocument();
    expect(onSelectSet).not.toHaveBeenCalled();
  });

  it("jumps to a node from the keyboard picker", async () => {
    const onSelectSet = vi.fn();
    await renderMap({ onSelectSet });
    await userEvent.click(screen.getByRole("combobox", { name: "Jump to node" }));
    await userEvent.click(screen.getByRole("option", { name: "router" }));
    expect(screen.getByText("router description")).toBeInTheDocument();
    expect(onSelectSet).toHaveBeenCalledWith("routing");
  });

  it("highlights the nodes the active set covers", async () => {
    await renderMap({ activeSet: "routing" });
    await waitFor(() => expect(mocks.toggleNodeClass).toHaveBeenCalledWith("router", "covered", true));
    expect(mocks.toggleNodeClass).toHaveBeenCalledWith("clarify", "covered", false);
  });

  it("zooms and switches line style", async () => {
    await renderMap();
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(mocks.zoom).toHaveBeenCalledWith(1.25);
    await userEvent.click(screen.getByRole("button", { name: "right-angle" }));
    expect(mocks.toggleEdgeClass).toHaveBeenLastCalledWith("right-angle", true);
  });

  it("Run button asks the dashboard to run the set, and is disabled while a run is active", async () => {
    const onRunSet = vi.fn();
    const { rerender } = await renderMap({ onRunSet });
    await tap("router");
    await userEvent.click(screen.getByRole("button", { name: "Run routing" }));
    expect(onRunSet).toHaveBeenCalledWith("routing");
    rerender(<WorkflowMap activeSet={null} onSelectSet={vi.fn()} onRunSet={onRunSet} running />);
    expect(screen.getByRole("button", { name: "Run routing" })).toBeDisabled();
  });

  it("lists manual scripts as plain text", async () => {
    await renderMap();
    await tap("recall");
    expect(screen.getByText("evals/semantic_memory.py")).toBeInTheDocument();
    expect(screen.getByText(/manual, not runnable/)).toBeInTheDocument();
  });

  it("shows the error when the fetch fails", async () => {
    mocks.fetchEvalWorkflow.mockRejectedValue(new Error("boom"));
    render(<WorkflowMap activeSet={null} onSelectSet={vi.fn()} onRunSet={vi.fn()} running={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });
});

describe("edgeBend", () => {
  it("puts a long edge's bend at the source lane and the target row", () => {
    const bend = edgeBend({ x: 0, y: 0 }, { x: 300, y: 400 });
    // Bend point (0, 400) projected onto the 500-long source→target line.
    expect(bend.weight).toBeCloseTo(0.64);
    expect(Math.abs(bend.distance)).toBeCloseTo(240);
  });

  it("arcs a short cross-lane edge and keeps the spine straight", () => {
    expect(edgeBend({ x: 0, y: 0 }, { x: 190, y: 72 }).distance).toBeCloseTo(0.15 * Math.hypot(190, 72));
    expect(edgeBend({ x: 0, y: 0 }, { x: 0, y: 500 })).toEqual({ distance: 0, weight: 0.5 });
  });
});

describe("nodeLabel", () => {
  it("breaks a name wider than the box and grows the box to fit every line", () => {
    const { label, height } = nodeLabel(node("synthesiser", "llm", 0, 0, [], ["org/a-model-name-much-wider-than-any-node-box"]) as never);
    const lines = label.split("\n");
    expect(lines.every((line) => line.length <= 24)).toBe(true);
    expect(lines.join("")).toBe("synthesisera-model-name-much-wider-than-any-node-box");
    expect(height).toBe(lines.length * 13 + 12);
  });
});

describe("bendThrough", () => {
  it("sets the control point so the curve's midpoint lands on the pointer", () => {
    // Pointer 50 above the midpoint of a flat line needs a control point 100 above it.
    const bend = bendThrough({ x: 0, y: 0 }, { x: 200, y: 0 }, { x: 100, y: -50 });
    expect(bend.weight).toBeCloseTo(0.5);
    expect(Math.abs(bend.distance)).toBeCloseTo(100);
  });
});
