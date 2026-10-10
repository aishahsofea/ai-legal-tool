import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantMessage } from "@/components/locus-workspace";
import type { Citation } from "@/lib/queryTransport";
import { fetchThread, fetchThreads } from "@/lib/threadsTransport";
import { useResearchThreads } from "./useResearchThreads";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

vi.mock("@/lib/threadsTransport", () => ({
  fetchThreads: vi.fn(),
  fetchThread: vi.fn(),
}));

vi.mock("@/lib/useQuery", () => ({
  useQuery: () => ({
    submit: vi.fn(),
    resume: vi.fn(),
    cancel: vi.fn(),
    status: "",
    response: "",
    citations: [],
    commentary: [],
    currency_labels: [],
    nodeRuns: [],
    isLoading: false,
    error: null,
    pendingQuestion: null,
  }),
}));

const CITATION: Citation = {
  act_number: "265",
  act_title: "Employment Act 1955",
  section_number: "60E",
  pdf_url: "https://example.com/act265.pdf",
  page_number: 4,
  receipt: { document_id: "doc-265", evidence: [{ claim: "98 days", quote: "ninety-eight days" }] },
};

const LISTED = { id: "t1", title: "Maternity leave", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-02T10:00:00Z" };

function stubServer() {
  vi.mocked(fetchThreads).mockResolvedValue([LISTED]);
  vi.mocked(fetchThread).mockResolvedValue({
    ...LISTED,
    messages: [
      { role: "user", content: "How long is maternity leave?" },
      { role: "assistant", content: "98 days.", citations: [CITATION], commentary: [], currency_labels: [] },
    ],
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("restoring threads", () => {
  it("lists the server's threads on mount without loading their turns", async () => {
    stubServer();
    const { result } = renderHook(() => useResearchThreads());

    await waitFor(() => expect(result.current.threads).toHaveLength(1));
    expect(result.current.threads[0].title).toBe("Maternity leave");
    expect(fetchThread).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });

  it("fills messages and sources when a listed thread is selected", async () => {
    stubServer();
    const { result } = renderHook(() => useResearchThreads());
    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    await act(() => result.current.selectThread("t1"));

    expect(result.current.activeThreadId).toBe("t1");
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(result.current.messages[1].citations).toEqual([CITATION]);
    expect(result.current.sources).toEqual([CITATION]);
    expect(result.current.citedCountLabel).toBe("1 citation · 1 source");
  });

  it("does not refetch a thread that is already loaded", async () => {
    stubServer();
    const { result } = renderHook(() => useResearchThreads());
    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    await act(() => result.current.selectThread("t1"));
    await act(async () => result.current.newThread());
    await act(() => result.current.selectThread("t1"));

    expect(fetchThread).toHaveBeenCalledTimes(1);
    expect(result.current.messages).toHaveLength(2);
  });

  it("opens a receipt from a restored citation", async () => {
    stubServer();
    const { result } = renderHook(() => useResearchThreads());
    await waitFor(() => expect(result.current.threads).toHaveLength(1));
    await act(() => result.current.selectThread("t1"));

    const onOpenReceipt = vi.fn();
    render(
      <AssistantMessage
        message={result.current.messages[1]}
        citedCountLabel={result.current.citedCountLabel}
        status=""
        isLoading={false}
        isTail
        reasoningOpen={false}
        onToggleReasoning={() => {}}
        statusHistory={[]}
        nodeRuns={[]}
        onOpenReceipt={onOpenReceipt}
      />,
    );
    await userEvent.click(screen.getByText("Open citation receipt"));

    expect(onOpenReceipt).toHaveBeenCalledWith(CITATION, 0, expect.any(HTMLElement));
  });

  it("stays on the current thread and reports an error when the fetch fails", async () => {
    stubServer();
    vi.mocked(fetchThread).mockRejectedValue(new Error("HTTP 500"));
    const { result } = renderHook(() => useResearchThreads());
    await waitFor(() => expect(result.current.threads).toHaveLength(1));

    await act(() => result.current.selectThread("t1"));

    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.loadError).toBe("Could not open that thread.");
  });
});
