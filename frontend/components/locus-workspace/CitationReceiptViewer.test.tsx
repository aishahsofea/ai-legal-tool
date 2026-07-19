import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Citation } from "@/lib/useQuery";
import { CitationReceiptViewer } from "./CitationReceiptViewer";
import { AssistantMessage } from "./Messages";

vi.mock("react-pdf", async () => {
  const React = await import("react");
  return {
    pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
    Document: ({ children, file, onLoadSuccess }: { children: React.ReactNode; file: string; onLoadSuccess: (value: { numPages: number }) => void }) => {
      const onLoadRef = React.useRef(onLoadSuccess);
      React.useEffect(() => onLoadRef.current({ numPages: 12 }), []);
      return <div data-testid="mock-document" data-file={file}>{children}</div>;
    },
    Page: ({ pageNumber, width }: { pageNumber: number; width: number }) => <div data-testid="mock-page" data-page={pageNumber} data-width={width} />,
  };
});

const evidence = [
  { claim: "The first legal claim.", quote: "First exact supporting words" },
  { claim: "The second legal claim.", quote: "Second exact supporting words" },
];

const PILOT: Citation = {
  act_number: "56",
  act_title: "EVIDENCE ACT 1950",
  section_number: "90A",
  pdf_url: "https://lom.agc.gov.my/latest.pdf",
  page_number: 3,
  receipt: { document_id: "act-56-reprint-2017-c11400ad", evidence },
};

const NON_PILOT: Citation = {
  act_number: "1",
  act_title: "NON PILOT ACT",
  section_number: "2",
  pdf_url: "https://lom.agc.gov.my/non-pilot.pdf",
  page_number: 4,
};

function response(payload: object, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  }));
}

function located(status: "matched" | "not_found" | "ambiguous", page = 7) {
  return {
    status,
    fallback_page: 3,
    document: {
      document_id: PILOT.receipt!.document_id,
      act_number: "56",
      act_title: "EVIDENCE ACT 1950",
      timeline_date: "2017-05-23",
      timeline_type: "REPRINT ONLINE",
      sha256: "c11400ad",
    },
    pages: status === "matched" ? [{
      page_number: page,
      rectangles: [{ x: 0.1, y: 0.2, width: 0.4, height: 0.03 }],
    }] : [],
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Citation Receipt integration", () => {
  it("opens the shared viewer from the inline pilot source action", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(located("matched"))));

    function Harness() {
      const [selected, setSelected] = useState<Citation | null>(null);
      return <>
        <AssistantMessage
          message={{ id: "m1", role: "assistant", content: "Section 90A applies.", createdAt: "10:00", citations: [PILOT] }}
          citedCountLabel="1 citation · 1 source"
          status=""
          isLoading={false}
          isTail
          reasoningOpen={false}
          onToggleReasoning={() => {}}
          statusHistory={[]}
          onOpenReceipt={(citation) => setSelected(citation)}
        />
        {selected && <CitationReceiptViewer citation={selected} onClose={() => setSelected(null)} />}
      </>;
    }

    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: /open citation receipt 1/i }));

    expect(await screen.findByRole("dialog", { name: /evidence act 1950/i })).toBeInTheDocument();
  });

  it("routes an unmodified in-prose pilot click through the shared opener", async () => {
    const openReceipt = vi.fn();
    render(<AssistantMessage
      message={{ id: "m2", role: "assistant", content: "Section 90A applies.", createdAt: "10:00", citations: [PILOT] }}
      citedCountLabel="1 citation · 1 source"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      onOpenReceipt={openReceipt}
    />);

    await userEvent.click(screen.getByRole("link", { name: "Section 90A" }));

    expect(openReceipt).toHaveBeenCalledWith(PILOT, 0, expect.any(HTMLElement));
  });

  it("leaves modified in-prose clicks to the real Official Source href", () => {
    const openReceipt = vi.fn();
    render(<AssistantMessage
      message={{ id: "m2b", role: "assistant", content: "Section 90A applies.", createdAt: "10:00", citations: [PILOT] }}
      citedCountLabel="1 citation · 1 source"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      onOpenReceipt={openReceipt}
    />);
    const proseLink = screen.getByRole("link", { name: "Section 90A" });

    fireEvent.click(proseLink, { ctrlKey: true });

    expect(openReceipt).not.toHaveBeenCalled();
    expect(proseLink).toHaveAttribute("href", `${PILOT.pdf_url}#page=3`);
    expect(proseLink).toHaveAttribute("target", "_blank");
  });

  it("preserves external-link behavior for a non-pilot citation", () => {
    render(<AssistantMessage
      message={{ id: "m3", role: "assistant", content: "Section 2 applies.", createdAt: "10:00", citations: [NON_PILOT] }}
      citedCountLabel="1 citation · 1 source"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      onOpenReceipt={vi.fn()}
    />);

    const external = screen.getByRole("link", { name: /open source 1/i });
    expect(external).toHaveAttribute("href", NON_PILOT.pdf_url);
    expect(external).toHaveAttribute("target", "_blank");
    expect(screen.queryByRole("button", { name: /open citation receipt/i })).not.toBeInTheDocument();
  });
});

describe("CitationReceiptViewer", () => {
  it("selects the matched page and renders only returned overlay rectangles", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(located("matched", 7))));
    render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "7"));
    expect(screen.getByTestId("receipt-highlight")).toHaveStyle({ left: "10%", top: "20%" });
    expect(screen.getByText(/verified passage located/i)).toBeInTheDocument();
  });

  it.each([
    ["not_found", "Exact passage could not be pinpointed."],
    ["ambiguous", "The passage appeared more than once, so no unique match was selected."],
  ] as const)("renders honest %s state without rectangles", async (status, message) => {
    vi.stubGlobal("fetch", vi.fn(() => response(located(status))));
    render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByTestId("receipt-highlight")).not.toBeInTheDocument();
    expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "3");
  });

  it("renders page-only state when no verified evidence exists", async () => {
    const emptyCitation = { ...PILOT, receipt: { ...PILOT.receipt!, evidence: [] } };
    vi.stubGlobal("fetch", vi.fn(() => response(located("not_found"))));
    render(<CitationReceiptViewer citation={emptyCitation} onClose={() => {}} />);

    expect(await screen.findByText("No verified passage was available.")).toBeInTheDocument();
    expect(screen.queryByTestId("receipt-highlight")).not.toBeInTheDocument();
  });

  it("selecting another Evidence Span requests and displays its location", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => response(located("matched", 7)))
      .mockImplementationOnce(() => response(located("matched", 9)));
    vi.stubGlobal("fetch", fetchMock);
    render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "7"));

    await userEvent.click(screen.getByRole("button", { name: "Evidence 2" }));

    await waitFor(() => expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "9"));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ evidence_quote: evidence[1].quote });
  });

  it("supports page navigation, page count, and zoom controls", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(located("matched", 7))));
    render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "7"));

    await userEvent.click(screen.getByRole("button", { name: "Next PDF page" }));
    expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "8");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(screen.getByRole("button", { name: "Reset zoom" })).toHaveTextContent("125%");
    expect(screen.getByText("Page 8 of 12")).toBeInTheDocument();
  });

  it("shows an API error and keeps the Official Source Link", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({}, 503)));
    render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 503");
    expect(screen.queryByTestId("receipt-highlight")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /check latest on agc/i })).toHaveAttribute("href", PILOT.pdf_url);
  });

  it("Escape closes and restores focus to the opening control", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response(located("matched"))));

    function Harness() {
      const [open, setOpen] = useState(false);
      const [opener, setOpener] = useState<HTMLElement | null>(null);
      return <>
        <button onClick={(event) => { setOpener(event.currentTarget); setOpen(true); }}>Open receipt</button>
        {open && <CitationReceiptViewer citation={PILOT} onClose={() => {
          setOpen(false);
          requestAnimationFrame(() => opener?.focus());
        }} />}
      </>;
    }

    render(<Harness />);
    const openButton = screen.getByRole("button", { name: "Open receipt" });
    await userEvent.click(openButton);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(openButton).toHaveFocus());
  });

  it("ignores a stale locator response after the selected citation changes", async () => {
    let resolveFirst!: (value: Response) => void;
    let resolveSecond!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    const second = new Promise<Response>((resolve) => { resolveSecond = resolve; });
    vi.stubGlobal("fetch", vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second));
    const { rerender } = render(<CitationReceiptViewer citation={PILOT} onClose={() => {}} />);
    const other = {
      ...PILOT,
      act_number: "265",
      act_title: "EMPLOYMENT ACT 1955",
      section_number: "19",
      receipt: { document_id: "act-265-reprint-2023-6fec2f07", evidence: [evidence[0]] },
    };

    rerender(<CitationReceiptViewer citation={other} onClose={() => {}} />);
    await act(async () => resolveSecond(new Response(JSON.stringify({
      ...located("matched", 9),
      document: { ...located("matched").document, document_id: other.receipt.document_id, act_number: "265", act_title: other.act_title },
    }), { status: 200 })));
    await waitFor(() => expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "9"));
    await act(async () => resolveFirst(new Response(JSON.stringify(located("matched", 7)), { status: 200 })));

    expect(screen.getByTestId("mock-page")).toHaveAttribute("data-page", "9");
    expect(screen.getByRole("dialog", { name: /employment act 1955/i })).toBeInTheDocument();
  });
});
