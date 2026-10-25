import { act, cleanup, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantMessage } from "@/components/locus-workspace";
import type { Citation } from "@/lib/queryTransport";
import { deleteThread, fetchThread, fetchThreads } from "@/lib/threadsTransport";
import { useResearchThreads } from "./useResearchThreads";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

vi.mock("@/lib/threadsTransport", () => ({
  fetchThreads: vi.fn(),
  fetchThread: vi.fn(),
  deleteThread: vi.fn(),
}));

const { submit } = vi.hoisted(() => ({ submit: vi.fn() }));

vi.mock("@/lib/useQuery", () => ({
  useQuery: () => ({
    submit,
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

describe("thread list status", () => {
  it("list status is loading until the fetch resolves", async () => {
    let resolve!: (items: (typeof LISTED)[]) => void;
    vi.mocked(fetchThreads).mockReturnValue(new Promise((r) => (resolve = r)));
    const { result } = renderHook(() => useResearchThreads());

    expect(result.current.threadListStatus).toBe("loading");
    await act(async () => resolve([LISTED]));

    expect(result.current.threadListStatus).toBe("ready");
  });

  it("list status is ready with an empty list", async () => {
    vi.mocked(fetchThreads).mockResolvedValue([]);
    const { result } = renderHook(() => useResearchThreads());

    await waitFor(() => expect(result.current.threadListStatus).toBe("ready"));
    expect(result.current.threads).toEqual([]);
  });

  it("list status is failed on rejection", async () => {
    vi.mocked(fetchThreads).mockRejectedValue(new Error("HTTP 500"));
    const { result } = renderHook(() => useResearchThreads());

    await waitFor(() => expect(result.current.threadListStatus).toBe("failed"));
    expect(result.current.loadError).toBe("Could not load your threads.");
  });
});

describe("opening a thread", () => {
  const LISTED_2 = { id: "t2", title: "Overtime pay", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-04T10:00:00Z" };

  function stored(item: typeof LISTED, question: string) {
    return { ...item, messages: [{ role: "user" as const, content: question }] };
  }

  function deferFetchThread() {
    const pending: Record<string, { resolve: (v: ReturnType<typeof stored>) => void; reject: (e: Error) => void }> = {};
    vi.mocked(fetchThread).mockImplementation(
      (id: string) => new Promise((resolve, reject) => (pending[id] = { resolve, reject })),
    );
    return pending;
  }

  async function mountWithTwoThreads() {
    vi.mocked(fetchThreads).mockResolvedValue([LISTED, LISTED_2]);
    const hook = renderHook(() => useResearchThreads());
    await waitFor(() => expect(hook.result.current.threads).toHaveLength(2));
    return hook;
  }

  it("blocks sending while a thread loads and keeps the typed text", async () => {
    deferFetchThread();
    const { result } = await mountWithTwoThreads();

    act(() => {
      result.current.setInput("draft question");
      void result.current.selectThread("t1");
    });
    await act(async () => {
      await result.current.submitQuery("x");
    });

    expect(submit).not.toHaveBeenCalled();
    expect(result.current.input).toBe("draft question");
  });

  it("marks the clicked thread loading and active before the fetch resolves", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();

    let selecting!: Promise<void>;
    act(() => {
      selecting = result.current.selectThread("t1");
    });

    expect(result.current.loadingThreadId).toBe("t1");
    expect(result.current.loadingThread?.title).toBe("Maternity leave");
    expect(result.current.threads.find((t) => t.id === "t1")?.active).toBe(true);
    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.messages).toEqual([]);

    await act(async () => {
      pending.t1.resolve(stored(LISTED, "Q1"));
      await selecting;
    });

    expect(result.current.loadingThreadId).toBeNull();
    expect(result.current.activeThreadId).toBe("t1");
    expect(result.current.messages.map((m) => m.content)).toEqual(["Q1"]);
  });

  it("superseded click never activates", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = result.current.selectThread("t1");
    });
    act(() => {
      second = result.current.selectThread("t2");
    });

    await act(async () => {
      pending.t1.resolve(stored(LISTED, "Q1"));
      await first;
    });
    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.loadingThreadId).toBe("t2");

    await act(async () => {
      pending.t2.resolve(stored(LISTED_2, "Q2"));
      await second;
    });
    expect(result.current.activeThreadId).toBe("t2");
    expect(result.current.loadingThreadId).toBeNull();
  });

  it("failed select clears loading and shows the error", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();
    let opening!: Promise<void>;
    act(() => {
      opening = result.current.selectThread("t1");
    });
    await act(async () => {
      pending.t1.resolve(stored(LISTED, "Q1"));
      await opening;
    });

    let failing!: Promise<void>;
    act(() => {
      failing = result.current.selectThread("t2");
    });
    expect(result.current.threads.find((t) => t.id === "t2")?.active).toBe(true);
    await act(async () => {
      pending.t2.reject(new Error("HTTP 500"));
      await failing;
    });

    expect(result.current.loadingThreadId).toBeNull();
    expect(result.current.loadError).toBe("Could not open that thread.");
    expect(result.current.activeThreadId).toBe("t1");
    expect(result.current.threads.map((t) => t.active)).toEqual([true, false]);
  });

  it("a new select clears the previous error", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();
    let failing!: Promise<void>;
    act(() => {
      failing = result.current.selectThread("t1");
    });
    await act(async () => {
      pending.t1.reject(new Error("HTTP 500"));
      await failing;
    });
    expect(result.current.loadError).toBe("Could not open that thread.");

    act(() => {
      void result.current.selectThread("t2");
    });

    expect(result.current.loadError).toBeNull();
  });

  it("repeat click on the loading thread fetches once", async () => {
    deferFetchThread();
    const { result } = await mountWithTwoThreads();

    act(() => {
      void result.current.selectThread("t1");
    });
    act(() => {
      void result.current.selectThread("t1");
    });

    expect(fetchThread).toHaveBeenCalledTimes(1);
  });

  it("newThread during a fetch drops it", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();
    let selecting!: Promise<void>;
    act(() => {
      selecting = result.current.selectThread("t1");
    });

    act(() => result.current.newThread());
    expect(result.current.loadingThreadId).toBeNull();

    await act(async () => {
      pending.t1.resolve(stored(LISTED, "Q1"));
      await selecting;
    });
    expect(result.current.activeThreadId).toBeNull();
  });

  it("stopQuery during a load keeps the loading row active", async () => {
    deferFetchThread();
    const { result } = await mountWithTwoThreads();
    await act(async () => {
      await result.current.submitQuery("first question");
    });
    act(() => {
      void result.current.selectThread("t1");
    });

    act(() => result.current.stopQuery());

    expect(result.current.loadingThreadId).toBe("t1");
    expect(result.current.threads.find((t) => t.id === "t1")?.active).toBe(true);
  });

  it("already-loaded thread switches without loading", async () => {
    const pending = deferFetchThread();
    const { result } = await mountWithTwoThreads();
    let opening!: Promise<void>;
    act(() => {
      opening = result.current.selectThread("t1");
    });
    await act(async () => {
      pending.t1.resolve(stored(LISTED, "Q1"));
      await opening;
    });
    act(() => result.current.newThread());

    let reselecting!: Promise<void>;
    act(() => {
      reselecting = result.current.selectThread("t1");
    });

    expect(result.current.loadingThreadId).toBeNull();
    await act(async () => {
      await reselecting;
    });
    expect(result.current.activeThreadId).toBe("t1");
    expect(fetchThread).toHaveBeenCalledTimes(1);
  });
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

describe("deleting a thread", () => {
  const LISTED_2 = { id: "t2", title: "Overtime pay", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-04T10:00:00Z" };

  async function mountWithTwoThreads() {
    stubServer();
    vi.mocked(fetchThreads).mockResolvedValue([LISTED, LISTED_2]);
    vi.mocked(deleteThread).mockResolvedValue(undefined);
    const hook = renderHook(() => useResearchThreads());
    await waitFor(() => expect(hook.result.current.threads).toHaveLength(2));
    return hook;
  }

  it("removes only the deleted inactive row and keeps the active thread", async () => {
    const { result } = await mountWithTwoThreads();
    await act(async () => result.current.selectThread("t1"));

    await act(async () => result.current.deleteThread("t2"));

    expect(deleteThread).toHaveBeenCalledWith("t2");
    expect(result.current.threads.map((t) => t.id)).toEqual(["t1"]);
    expect(result.current.activeThreadId).toBe("t1");
  });

  it("deleting the active thread returns to the empty state", async () => {
    const { result } = await mountWithTwoThreads();
    await act(async () => result.current.selectThread("t1"));
    expect(result.current.messages.length).toBeGreaterThan(0);

    await act(async () => result.current.deleteThread("t1"));

    expect(result.current.threads.map((t) => t.id)).toEqual(["t2"]);
    expect(result.current.activeThread).toBeNull();
    expect(result.current.messages).toEqual([]);
  });

  it("a fetch still pending for the deleted thread cannot bring it back", async () => {
    const { result } = await mountWithTwoThreads();
    let resolveFetch!: (v: Awaited<ReturnType<typeof fetchThread>>) => void;
    vi.mocked(fetchThread).mockImplementation(() => new Promise((r) => (resolveFetch = r)));
    act(() => {
      void result.current.selectThread("t1");
    });

    await act(async () => result.current.deleteThread("t1"));
    await act(async () => resolveFetch({ ...LISTED, messages: [{ role: "user", content: "q" }] }));

    expect(result.current.threads.map((t) => t.id)).toEqual(["t2"]);
    expect(result.current.activeThreadId).toBeNull();
    expect(result.current.loadingThreadId).toBeNull();
  });

  it("a rejected delete keeps the row and sets the error", async () => {
    const { result } = await mountWithTwoThreads();
    vi.mocked(deleteThread).mockRejectedValue(new Error("HTTP 500"));

    await act(async () => result.current.deleteThread("t2"));

    expect(result.current.threads.map((t) => t.id)).toEqual(["t1", "t2"]);
    expect(result.current.loadError).toBe("Could not delete that thread.");
  });
});
