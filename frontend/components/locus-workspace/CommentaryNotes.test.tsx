import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CommentaryNote } from "@/lib/useQuery";
import type { Message } from "./types";
import { AssistantMessage } from "./Messages";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

const NOTES: CommentaryNote[] = [
  {
    url: "https://skrine.com/insights/act-265-amendments",
    title: "What the 2022 amendments change for employers",
    publisher: "skrine.com",
    published_date: "2022-11-03",
    retrieved_at: "2026-09-20T00:00:00Z",
    snippet: "A short practitioner note on the amendment's practical effect.",
  },
];

const CITATIONS: NonNullable<Message["citations"]> = [
  { act_number: "265", act_title: "Employment Act 1955", section_number: "90A", pdf_url: "https://example.com/act.pdf", page_number: 12 },
];

function renderMessage({
  citations = [],
  commentary = [],
}: { citations?: Message["citations"]; commentary?: Message["commentary"] }) {
  return render(
    <AssistantMessage
      message={{
        id: "m1",
        role: "assistant",
        content: "Section 90A applies.",
        createdAt: "10:30",
        citations,
        commentary,
      }}
      citedCountLabel="0 sources"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      nodeRuns={[]}
      onOpenReceipt={() => {}}
    />,
  );
}

afterEach(cleanup);

describe("commentary block", () => {
  it("renders nothing when there is no commentary", () => {
    renderMessage({});
    expect(screen.queryByText("COMMENTARY")).toBeNull();
  });

  it("shows publisher, title, date, and snippet for each note", () => {
    renderMessage({ commentary: NOTES });
    expect(screen.getByText("COMMENTARY")).toBeTruthy();
    expect(screen.getByText("skrine.com")).toBeTruthy();
    expect(screen.getByText("What the 2022 amendments change for employers")).toBeTruthy();
    expect(screen.getByText("2022-11-03")).toBeTruthy();
    expect(screen.getByText("A short practitioner note on the amendment's practical effect.")).toBeTruthy();
  });

  it("links straight to the publisher, never to a receipt", () => {
    renderMessage({ commentary: NOTES });
    const link = screen.getByRole("link", { name: /open publisher site/i });
    expect(link.getAttribute("href")).toBe(NOTES[0].url);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.queryByText(/open citation receipt/i)).toBeNull();
  });

  it("never uses the word 'source' in the commentary block, to keep it distinct from citations", () => {
    renderMessage({ commentary: NOTES });
    const section = screen.getByLabelText("Background commentary, not a legal citation");
    expect(section.textContent?.toLowerCase()).not.toContain("source");
  });

  it("keeps the commentary block structurally separate from SOURCES USED", () => {
    renderMessage({ citations: CITATIONS, commentary: NOTES });

    const sourcesSection = screen.getByText("SOURCES USED").closest("section");
    const commentarySection = screen.getByText("COMMENTARY").closest("section");
    expect(sourcesSection).not.toBeNull();
    expect(commentarySection).not.toBeNull();
    expect(sourcesSection).not.toBe(commentarySection);
    expect(commentarySection?.contains(sourcesSection)).toBe(false);
    expect(sourcesSection?.contains(commentarySection)).toBe(false);
  });

  it("omits the commentary block when no notes arrive, even with citations present", () => {
    renderMessage({ citations: CITATIONS, commentary: [] });
    expect(screen.getByText("SOURCES USED")).toBeTruthy();
    expect(screen.queryByText("COMMENTARY")).toBeNull();
  });
});
