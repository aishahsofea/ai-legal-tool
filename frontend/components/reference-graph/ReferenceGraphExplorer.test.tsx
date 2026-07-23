import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReferenceGraphExplorer } from "./ReferenceGraphExplorer";

const mocks = vi.hoisted(() => ({
  fetchNeighborhood: vi.fn(),
  nodeTap: { current: undefined as ((event: { target: { id: () => string } }) => void) | undefined },
  cytoscapeOptions: { current: undefined as { elements?: Array<{ data: { id: string; label?: string } }> } | undefined },
}));

vi.mock("@/lib/referenceGraphTransport", async () => {
  const actual = await vi.importActual<typeof import("@/lib/referenceGraphTransport")>("@/lib/referenceGraphTransport");
  return { ...actual, fetchNeighborhood: mocks.fetchNeighborhood };
});

vi.mock("cytoscape", () => ({
  default: vi.fn((options) => {
    mocks.cytoscapeOptions.current = options;
    return ({
    destroy: vi.fn(),
    layout: () => ({ run: vi.fn() }),
    on: (_event: string, _selector: string, handler: typeof mocks.nodeTap.current) => { mocks.nodeTap.current = handler; },
    });
  }),
}));

const documentId = "act-265-reprint-2023-6fec2f07";
const focus = "act:265/section:60D";

describe("reference graph explorer", () => {
  it("loads lazily, supports Explore/Trace, focus history, and direct evidence receipts", async () => {
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [
        { provision_id: focus, version_id: "v1", label: "Section 60D", kind: "section", page_start: 60, page_end: 63 },
        { provision_id: "act:265/section:4", version_id: "v2", label: "Section 4", kind: "section", page_start: 22, page_end: 23 },
      ],
      edges: [{ edge_id: "edge:1", source_provision_id: focus, target_provision_id: "act:265/section:4", relationship: "explicit_reference", reference_kind: "section", evidence: { text: "section 4", start_offset: 0, end_offset: 9, pages: [{ page_number: 60, rectangles: [] }] } }],
    });
    const onNavigation = vi.fn();
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} onNavigation={onNavigation} />);

    expect(await screen.findByTestId("reference-graph-canvas")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open receipt page 60" })).toHaveAttribute("href", `/receipts/${documentId}/pdf#page=60`);
    await userEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(screen.getByRole("button", { name: "Trace" })).toHaveAttribute("aria-pressed", "true");

    await waitFor(() => expect(mocks.nodeTap.current).toBeTypeOf("function"));
    mocks.nodeTap.current?.({ target: { id: () => "act:265/section:4" } });
    await userEvent.click(screen.getByRole("button", { name: "Focus here" }));
    await waitFor(() => expect(mocks.fetchNeighborhood).toHaveBeenCalledWith(documentId, "act:265/section:4", expect.any(AbortSignal)));
    expect(screen.getByRole("button", { name: "Back" })).not.toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(mocks.fetchNeighborhood).toHaveBeenCalledWith(documentId, focus, expect.any(AbortSignal)));
  });

  it("uses the exact pending-index message", async () => {
    mocks.fetchNeighborhood.mockResolvedValue({ status: "not_indexed", document_id: documentId });
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} />);
    expect(await screen.findByText("Reference graph not yet indexed for this snapshot.")).toBeInTheDocument();
  });

  it("renders an explicit unindexed boundary for a cross-Act target", async () => {
    mocks.fetchNeighborhood.mockResolvedValue({
      status: "available", document_id: documentId, focus_provision_id: focus,
      nodes: [{ provision_id: focus, version_id: "v1", label: "Section 60D", kind: "section", page_start: 60, page_end: 63 }],
      edges: [{ edge_id: "edge:cross", source_provision_id: focus, target_provision_id: "act:369/section:8", relationship: "explicit_reference", reference_kind: "section", evidence: { text: "section 8", start_offset: 0, end_offset: 9, pages: [{ page_number: 60, rectangles: [] }] } }],
    });
    render(<ReferenceGraphExplorer documentId={documentId} focusProvisionId={focus} />);
    await screen.findByTestId("reference-graph-canvas");
    await waitFor(() => expect(mocks.cytoscapeOptions.current).toBeDefined());
    expect(mocks.cytoscapeOptions.current?.elements?.find((item) => item.data.id === "act:369/section:8")?.data.label).toContain("Not yet indexed");
  });
});
