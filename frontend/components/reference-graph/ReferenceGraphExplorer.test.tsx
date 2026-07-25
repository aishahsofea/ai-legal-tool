import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fixedPresetPositions, ReferenceGraphExplorer } from "./ReferenceGraphExplorer";

const mocks = vi.hoisted(() => ({
  fetchNeighborhood: vi.fn(),
  fetchComparison: vi.fn(),
  fetchSnapshots: vi.fn(),
  nodeTap: { current: undefined as ((event: { target: { id: () => string } }) => void) | undefined },
  cytoscapeOptions: { current: undefined as { elements?: Array<{ data: { id: string; label?: string }; position?: { x: number; y: number } }> } | undefined },
  destroy: vi.fn(),
}));

vi.mock("@/lib/referenceGraphTransport", async () => {
  const actual = await vi.importActual<typeof import("@/lib/referenceGraphTransport")>("@/lib/referenceGraphTransport");
  return {
    ...actual,
    fetchNeighborhood: mocks.fetchNeighborhood,
    fetchComparison: mocks.fetchComparison,
    fetchSnapshots: mocks.fetchSnapshots,
  };
});

vi.mock("cytoscape", () => ({
  default: vi.fn((options) => {
    mocks.cytoscapeOptions.current = options;
    return ({
      destroy: mocks.destroy,
      on: (_event: string, _selector: string, handler: typeof mocks.nodeTap.current) => { mocks.nodeTap.current = handler; },
    });
  }),
}));

const documentId = "act-265-reprint-2023-6fec2f07";
const compareDocumentId = "act-265-en-sha256-compare";
const focus = "act:265/section:60D";
const node = (id: string, version: string, label: string) => ({
  provision_id: id, version_id: version, label, kind: "section", page_start: 60, page_end: 63,
});
const edge = (id: string, text: string, page: number) => ({
  edge_id: id,
  source_provision_id: focus,
  target_provision_id: "act:265/section:4",
  relationship: "explicit_reference",
  reference_kind: "section",
  evidence: { text, start_offset: 0, end_offset: text.length, pages: [{ page_number: page, rectangles: [] }] },
});

function snapshots() {
  return {
    status: "available",
    comparison_enabled: true,
    snapshots: [
      { document_id: documentId, corpus_document_id: "corpus-base", act_number: "265", act_title: "EMPLOYMENT ACT 1955", language: "en", snapshot_date: "01/02/2023", snapshot_type: "REPRINT ONLINE", source_url: "https://example.test/base", sha256: "a".repeat(64), byte_size: 100, page_count: 127, receipt_path: `/receipts/${documentId}/pdf` },
      { document_id: compareDocumentId, corpus_document_id: "corpus-compare", act_number: "265", act_title: "EMPLOYMENT ACT 1955", language: "en", snapshot_date: "02/09/2023", snapshot_type: "REPRINT", source_url: "https://example.test/compare", sha256: "b".repeat(64), byte_size: 101, page_count: 121, receipt_path: `/receipts/${compareDocumentId}/pdf` },
    ],
  };
}

describe("reference graph explorer", () => {
  beforeEach(() => {
    mocks.destroy.mockClear();
    mocks.nodeTap.current = undefined;
    mocks.cytoscapeOptions.current = undefined;
  });

  it("loads lazily, preserves Phase 1 navigation, and emits push/replace URL intent", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [node(focus, "v1", "Section 60D"), node("act:265/section:4", "v2", "Section 4")],
      edges: [edge("edge:1", "section 4", 60)],
    });
    const onStateChange = vi.fn();
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} onStateChange={onStateChange} />);

    expect(await screen.findByTestId("reference-graph-canvas")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open base receipt page 60" })).toHaveAttribute("href", `http://localhost:8000/receipts/${documentId}/pdf#page=60`);
    await userEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({ layout: "trace" }), "replace");

    await waitFor(() => expect(mocks.nodeTap.current).toBeTypeOf("function"));
    mocks.nodeTap.current?.({ target: { id: () => "act:265/section:4" } });
    await userEvent.click(screen.getByRole("button", { name: "Focus here" }));
    await waitFor(() => expect(mocks.fetchNeighborhood).toHaveBeenCalledWith(documentId, "act:265/section:4", expect.any(AbortSignal)));
    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({ focusProvisionId: "act:265/section:4" }), "push");
  });

  it("uses the exact Phase 1 pending-index message", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchNeighborhood.mockResolvedValue({ status: "not_indexed", document_id: documentId });
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} />);
    expect(await screen.findByText("Reference graph not yet indexed for this snapshot.")).toBeInTheDocument();
  });

  it("renders an explicit unindexed boundary for a cross-Act target", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [node(focus, "v1", "Section 60D")],
      edges: [{ ...edge("edge:cross", "section 8", 60), target_provision_id: "act:369/section:8" }],
    });
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} />);
    await screen.findByTestId("reference-graph-canvas");
    await waitFor(() => expect(mocks.cytoscapeOptions.current).toBeDefined());
    expect(mocks.cytoscapeOptions.current?.elements?.find((item) => item.data.id === "act:369/section:8")?.data.label).toContain("Not indexed");
  });

  it("shows an accessible comparison legend, fixed positions, and independent receipts", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchComparison.mockResolvedValue({
      status: "available",
      base_document_id: documentId,
      compare_document_id: compareDocumentId,
      focus_provision_id: focus,
      focus_presence: { base: true, compare: true },
      counts: { added: 0, removed: 0, unchanged: 1 },
      nodes: [
        { provision_id: focus, presence: "both", base_node: node(focus, "base-v", "Section 60D"), compare_node: node(focus, "compare-v", "Section 60D") },
        { provision_id: "act:265/section:4", presence: "both", base_node: node("act:265/section:4", "base-4", "Section 4"), compare_node: node("act:265/section:4", "compare-4", "Section 4") },
      ],
      references: [{
        logical_reference_id: "logical:1",
        logical_key: { source_provision_id: focus, target_provision_id: "act:265/section:4", reference_kind: "section", relationship: "explicit_reference", literal_wording: "section 4" },
        occurrence_ordinal: 1,
        status: "unchanged",
        base_edge: edge("edge:base", "section 4", 60),
        compare_edge: edge("edge:compare", "section 4", 55),
      }],
    });
    const onStateChange = vi.fn();
    render(
      <ReferenceGraphExplorer
        documentId={documentId}
        compareDocumentId={compareDocumentId}
        focusProvisionId={focus}
        onStateChange={onStateChange}
      />,
    );

    expect(await screen.findByLabelText("Comparison legend")).toHaveTextContent("Added (0)");
    expect(screen.getByRole("link", { name: "Open base receipt page 60" })).toHaveAttribute("href", `http://localhost:8000/receipts/${documentId}/pdf#page=60`);
    expect(screen.getByRole("link", { name: "Open comparison receipt page 55" })).toHaveAttribute("href", `http://localhost:8000/receipts/${compareDocumentId}/pdf#page=55`);
    await waitFor(() => expect(mocks.cytoscapeOptions.current).toBeDefined());
    const before = mocks.cytoscapeOptions.current?.elements?.filter((item) => item.position).map((item) => [item.data.id, item.position]);
    await userEvent.click(screen.getByRole("button", { name: /base/i }));
    expect(onStateChange).toHaveBeenCalledWith(
      expect.objectContaining({ view: "base" }),
      "replace",
    );
    await waitFor(() => {
      const after = mocks.cytoscapeOptions.current?.elements?.filter((item) => item.position).map((item) => [item.data.id, item.position]);
      expect(after).toEqual(before);
    });
    await userEvent.click(screen.getByRole("button", { name: /compare/i }));
    await waitFor(() => {
      const after = mocks.cytoscapeOptions.current?.elements?.filter((item) => item.position).map((item) => [item.data.id, item.position]);
      expect(after).toEqual(before);
    });
    await userEvent.click(screen.getByRole("button", { name: /overlay/i }));
    await waitFor(() => {
      const after = mocks.cytoscapeOptions.current?.elements?.filter((item) => item.position).map((item) => [item.data.id, item.position]);
      expect(after).toEqual(before);
    });
  });

  it("computes deterministic preset positions independent of input order", () => {
    const references = [{ source: focus, target: "act:265/section:4" }];
    expect(fixedPresetPositions([focus, "act:265/section:4"], focus, "trace", references)).toEqual(
      fixedPresetPositions(["act:265/section:4", focus], focus, "trace", references),
    );
  });

  it("never renders unavailable comparison snapshots as empty graphs", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchComparison.mockResolvedValue({
      status: "not_indexed_compare",
      base_document_id: documentId,
      compare_document_id: compareDocumentId,
    });
    render(<ReferenceGraphExplorer documentId={documentId} compareDocumentId={compareDocumentId} focusProvisionId={focus} />);
    expect(await screen.findByText("Reference graph not yet indexed for the comparison snapshot.")).toBeInTheDocument();
    expect(screen.queryByTestId("reference-graph-canvas")).not.toBeInTheDocument();
  });

  it("delegates Back to browser history in route-controlled mode", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [node(focus, "v1", "Section 60D")], edges: [],
    });
    const historyBack = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} onStateChange={vi.fn()} />);
    await screen.findByTestId("reference-graph-canvas");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(historyBack).toHaveBeenCalledOnce();
    historyBack.mockRestore();
  });

  it("destroys the lazy Cytoscape instance on unmount", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [node(focus, "v1", "Section 60D")], edges: [],
    });
    const rendered = render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} />);
    await screen.findByTestId("reference-graph-canvas");
    await waitFor(() => expect(mocks.cytoscapeOptions.current).toBeDefined());
    rendered.unmount();
    expect(mocks.destroy).toHaveBeenCalled();
  });

  it("preserves the complete comparison state when opening the larger view", async () => {
    mocks.fetchSnapshots.mockResolvedValue(snapshots());
    mocks.fetchComparison.mockResolvedValue({
      status: "not_indexed_compare",
      base_document_id: documentId,
      compare_document_id: compareDocumentId,
    });
    render(
      <ReferenceGraphExplorer
        documentId={documentId}
        compareDocumentId={compareDocumentId}
        focusProvisionId={focus}
        initialLayout="trace"
        initialView="compare"
      />,
    );
    const href = screen.getByRole("link", { name: "Open larger" }).getAttribute("href");
    const url = new URL(href ?? "", "https://example.test");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      document_id: documentId,
      focus_provision_id: focus,
      layout: "trace",
      overlay: "compare",
      compare_document_id: compareDocumentId,
    });
  });
});
