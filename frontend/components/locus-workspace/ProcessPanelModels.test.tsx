import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NodeRun } from "@/lib/useQuery";
import { AssistantMessage } from "./Messages";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

const message = {
  id: "m1",
  role: "assistant" as const,
  content: "Section 90A applies.",
  createdAt: "10:30",
  citations: [],
};

function renderPanel({
  nodeRuns = [],
  statusHistory = [],
  reasoningOpen = true,
}: { nodeRuns?: NodeRun[]; statusHistory?: string[]; reasoningOpen?: boolean }) {
  return render(
    <AssistantMessage
      message={message}
      citedCountLabel="0 sources"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={reasoningOpen}
      onToggleReasoning={() => {}}
      statusHistory={statusHistory}
      nodeRuns={nodeRuns}
      onOpenReceipt={() => {}}
    />,
  );
}

const RUNS: NodeRun[] = [
  { name: "router", model: "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", duration_ms: 412 },
  { name: "synthesiser", model: "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B", duration_ms: 2410 },
];

afterEach(cleanup);

describe("PROCESS panel model rows", () => {
  it("shows each node with the model it ran", () => {
    renderPanel({ nodeRuns: RUNS });
    expect(screen.getByText("router")).toBeTruthy();
    expect(screen.getByText("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")).toBeTruthy();
    expect(screen.getByText("synthesiser")).toBeTruthy();
    expect(screen.getByText("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B")).toBeTruthy();
  });

  it("renders rows in execution order", () => {
    renderPanel({ nodeRuns: RUNS });
    const rendered = screen.getAllByText(/^(router|synthesiser)$/).map((el) => el.textContent);
    expect(rendered).toEqual(["router", "synthesiser"]);
  });

  it("keeps both rows when a retry reruns the same node on the same model", () => {
    renderPanel({
      nodeRuns: [
        { name: "synthesiser", model: "m", duration_ms: 2000 },
        { name: "synthesiser", model: "m", duration_ms: 2200 },
      ],
    });
    expect(screen.getAllByText("synthesiser")).toHaveLength(2);
  });

  it("formats sub-second calls in ms and longer ones in seconds", () => {
    renderPanel({ nodeRuns: RUNS });
    expect(screen.getByText("412ms")).toBeTruthy();
    expect(screen.getByText("2.4s")).toBeTruthy();
  });

  it("leaves the collapsed step count to status steps alone", () => {
    // The header reports STEPS. Model rows sit in their own list below, so adding
    // them must not inflate that number.
    renderPanel({ nodeRuns: RUNS, statusHistory: ["Classifying query...", "Drafting response..."] });
    expect(screen.getByText("2 STEPS")).toBeTruthy();
  });

  it("hides the rows while the panel is collapsed", () => {
    renderPanel({ nodeRuns: RUNS, reasoningOpen: false });
    expect(screen.queryByText("MODELS")).toBeNull();
    expect(screen.queryByText("router")).toBeNull();
  });

  it("renders no MODELS group when no node reported", () => {
    renderPanel({ nodeRuns: [], statusHistory: ["Classifying query..."] });
    expect(screen.queryByText("MODELS")).toBeNull();
  });

  it("still shows the panel when only node rows arrived", () => {
    renderPanel({ nodeRuns: RUNS, statusHistory: [] });
    expect(screen.getByText("MODELS")).toBeTruthy();
    expect(screen.getByText("0 STEPS")).toBeTruthy();
  });
});
