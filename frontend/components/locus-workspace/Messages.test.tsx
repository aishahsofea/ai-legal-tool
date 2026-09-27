import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Message } from "./types";
import { AssistantMessage } from "./Messages";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

// Shaped exactly like a real synthesiser citation for a Schedule item (#171):
// section_number is "" (ADR 0018) and path carries the only identifier.
const SCHEDULE_CITATION: NonNullable<Message["citations"]>[number] = {
  act_number: "512",
  act_title: "GENEVA CONVENTIONS ACT 1962",
  section_number: "",
  path: "sched.2/art.1",
  pdf_url: "https://example.com/act512.pdf",
  page_number: 53,
};

const BODY_CITATION: NonNullable<Message["citations"]>[number] = {
  act_number: "56",
  act_title: "Evidence Act 1950",
  section_number: "90A",
  pdf_url: "https://example.com/act56.pdf",
  page_number: 12,
};

function renderMessage(citations: Message["citations"]) {
  return render(
    <AssistantMessage
      message={{
        id: "m1",
        role: "assistant",
        content: "Article 1 applies.",
        createdAt: "10:30",
        citations,
        currency_labels: [],
      }}
      citedCountLabel="1 source"
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

describe("citation key rendering (#171)", () => {
  it("renders a Schedule citation's path in the source map badge, not a blank key", () => {
    renderMessage([SCHEDULE_CITATION]);
    expect(screen.getByText("§ sched.2/art.1")).toBeTruthy();
  });

  it("renders a Schedule citation's path in the sources-used list, not a blank key", () => {
    renderMessage([SCHEDULE_CITATION]);
    expect(screen.getByText("[1] § sched.2/art.1")).toBeTruthy();
  });

  it("still renders a body citation's own section_number unchanged", () => {
    renderMessage([BODY_CITATION]);
    expect(screen.getByText("§ 90A")).toBeTruthy();
    expect(screen.getByText("[1] § 90A")).toBeTruthy();
  });
});
