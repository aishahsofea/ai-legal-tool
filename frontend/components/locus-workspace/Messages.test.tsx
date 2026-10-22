import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VERIFY_CAVEAT } from "@/lib/threadMarkdown";
import type { Message } from "./types";
import { AssistantMessage, UserMessage } from "./Messages";

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

function renderMessage(citations: Message["citations"], content = "Article 1 applies.", isLoading = false) {
  return render(
    <AssistantMessage
      message={{
        id: "m1",
        role: "assistant",
        content,
        createdAt: "10:30",
        citations,
        currency_labels: [],
      }}
      citedCountLabel="1 source"
      status=""
      isLoading={isLoading}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      nodeRuns={[]}
      onOpenReceipt={() => {}}
    />,
  );
}

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

afterEach(cleanup);

describe("copy controls", () => {
  it("copies only the answer text of a response", async () => {
    renderMessage([BODY_CITATION], "Section **90A** applies.");
    fireEvent.click(screen.getByRole("button", { name: "Copy response" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain("Section 90A applies.");
    expect(copied).not.toContain("SOURCES USED");
    expect(copied).not.toContain("SOURCE MAP");
  });

  it("shows Copied after a successful copy", async () => {
    renderMessage([], "Answer.");
    fireEvent.click(screen.getByRole("button", { name: "Copy response" }));
    await waitFor(() => expect(screen.getAllByText("Copied").length).toBeGreaterThan(0));
  });

  it("copies a user message verbatim, newlines included", async () => {
    render(<UserMessage message={{ id: "u1", role: "user", content: "line one\nline two", createdAt: "10:29" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("line one\nline two"));
  });

  it("renders no Copy button on an empty streaming placeholder", () => {
    renderMessage([], "", true);
    expect(screen.queryByRole("button", { name: "Copy response" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Message actions" })).toBeNull();
  });

  it("no longer renders the stub actions", () => {
    renderMessage([], "Answer.");
    for (const label of ["Save as memo", "Highlight passage", "Cite all"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
  });
});

describe("icon buttons", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  });

  it("shows a copy icon, no visible word, and a title", () => {
    renderMessage([], "Answer.");
    const button = screen.getByRole("button", { name: "Copy response" });
    expect(button.querySelector('svg[data-icon="copy"]')).not.toBeNull();
    expect(button.textContent).toBe("");
    expect(button.getAttribute("title")).toBe("Copy response");
  });

  it("shows a share icon, no visible word, and a title", () => {
    renderMessage([], "Answer.");
    const button = screen.getByRole("button", { name: "Share response" });
    expect(button.querySelector('svg[data-icon="share"]')).not.toBeNull();
    expect(button.textContent).toBe("");
    expect(button.getAttribute("title")).toBe("Share response");
  });

  it("swaps the copy icon for a check and retitles after click", async () => {
    render(<UserMessage message={{ id: "u1", role: "user", content: "hi", createdAt: "10:29" }} />);
    const button = screen.getByRole("button", { name: "Copy message" });
    fireEvent.click(button);
    await waitFor(() => expect(button.querySelector('svg[data-icon="check"]')).not.toBeNull());
    expect(button.getAttribute("title")).toBe("Copied");
    expect(button.querySelector('svg[data-icon="copy"]')).toBeNull();
  });

  it("swaps the share icon for a check and retitles after click", async () => {
    renderMessage([], "Answer.");
    const button = screen.getByRole("button", { name: "Share response" });
    fireEvent.click(button);
    await waitFor(() => expect(button.querySelector('svg[data-icon="check"]')).not.toBeNull());
    expect(button.getAttribute("title")).toBe("Copied");
  });
});

describe("user message selection", () => {
  it("bubble overrides the selection colour so highlight shows on its background", () => {
    render(<UserMessage message={{ id: "u1", role: "user", content: "select me", createdAt: "10:29" }} />);
    const bubble = screen.getByText("select me").parentElement;
    expect(bubble?.className).toContain("selection:bg-(--accent-line)");
  });
});

describe("share control", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  });

  it("copies the response Markdown when navigator.share is missing", async () => {
    renderMessage([BODY_CITATION], "Section 90A applies.");
    fireEvent.click(screen.getByRole("button", { name: "Share response" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const shared = writeText.mock.calls[0][0] as string;
    expect(shared).toContain("Section 90A applies.");
    expect(shared).toContain("**Sources**");
    expect(shared).toContain(VERIFY_CAVEAT);
    await waitFor(() => expect(screen.getAllByText("Copied").length).toBeGreaterThan(0));
  });

  it("renders no Share button on an empty streaming placeholder", () => {
    renderMessage([], "", true);
    expect(screen.queryByRole("button", { name: "Share response" })).toBeNull();
  });
});

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
