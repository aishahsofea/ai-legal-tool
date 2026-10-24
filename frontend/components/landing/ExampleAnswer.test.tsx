import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Message } from "@/components/locus-workspace/types";
import { summarizeSources } from "@/lib/useResearchThreads";
import { ExampleAnswer } from "./ExampleAnswer";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

const META = { threadId: "thread-1", producedOn: "24 Oct 2026" };

const MESSAGES: Message[] = [
  { id: "example-user", role: "user", content: "Is a computer printout admissible?", createdAt: "24 Oct" },
  {
    id: "example-assistant",
    role: "assistant",
    content: "Yes, under section 90A [1] and section 3 [2].",
    createdAt: "24 Oct",
    currency_labels: [],
    citations: [
      {
        act_number: "56",
        act_title: "EVIDENCE ACT 1950",
        section_number: "90A",
        pdf_url: "https://example.com/act56.pdf",
        page_number: 12,
        receipt: { document_id: "act-56", extraction_id: "ext-1", evidence: [{ claim: "Claim.", quote: "Quote" }] },
      },
      {
        act_number: "56",
        act_title: "EVIDENCE ACT 1950",
        section_number: "3",
        pdf_url: "https://example.com/act56.pdf",
        page_number: 4,
      },
    ],
  },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ExampleAnswer", () => {
  it("labels the answer as saved with its production date", () => {
    render(<ExampleAnswer meta={META} messages={MESSAGES} />);
    expect(screen.getByText("Saved example · produced 24 Oct 2026")).toBeTruthy();
  });

  it("shows each citation's Act and page under SOURCES USED", () => {
    render(<ExampleAnswer meta={META} messages={MESSAGES} />);
    const sources = screen.getByText("SOURCES USED").closest("section") as HTMLElement;
    expect(within(sources).getAllByText(/Evidence Act 1950/i).length).toBeGreaterThanOrEqual(2);
    expect(sources.textContent).toContain("12");
    expect(sources.textContent).toContain("4");
  });

  it("uses the workspace cited-count label", () => {
    render(<ExampleAnswer meta={META} messages={MESSAGES} />);
    expect(screen.getByText(summarizeSources(MESSAGES[1].citations!).toUpperCase())).toBeTruthy();
  });

  it("makes no network call at mount", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ExampleAnswer meta={META} messages={MESSAGES} />);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens the receipt in a modal dialog and closes it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 404 })));
    render(<ExampleAnswer meta={META} messages={MESSAGES} />);
    fireEvent.click(screen.getAllByRole("button", { name: /Open Citation Receipt 1/ })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    fireEvent.click(screen.getAllByRole("button", { name: "Close Citation Receipt" })[0]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
