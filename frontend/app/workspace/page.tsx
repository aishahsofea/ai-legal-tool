"use client";

import {
  type CSSProperties,
  type FormEvent,
  Suspense,
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import {
  Composer,
  ConversationHeader,
  EmptyState,
  AssistantMessage,
  ThreadSidebar,
  UserMessage,
} from "@/components/conversation";
import { useResearchThreads } from "@/lib/useResearchThreads";
import type { Citation } from "@/lib/useQuery";
import {
  DEFAULT_RECEIPT_PANE_WIDTH,
  ReceiptPaneResizer,
  clampReceiptPaneWidth,
} from "@/components/locus-workspace/ReceiptPaneResizer";

const CitationReceiptViewer = dynamic(
  () => import("@/components/locus-workspace/CitationReceiptViewer").then((module) => module.CitationReceiptViewer),
  { ssr: false },
);

type ReceiptSelection = {
  citation: Citation;
  evidenceIndex: number;
  opener: HTMLElement;
};

const DESKTOP_RECEIPT_QUERY = "(min-width: 1200px)";
const RECEIPT_WIDTH_STORAGE_KEY = "locus.receipt-pane-width.v1";

function subscribeViewport(callback: () => void) {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

function getViewportWidth() {
  return window.innerWidth;
}

function getServerViewportWidth() {
  return 1440;
}

function subscribeDesktopReceiptPane(callback: () => void) {
  const query = window.matchMedia(DESKTOP_RECEIPT_QUERY);
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

function getDesktopReceiptPaneSnapshot() {
  return window.matchMedia(DESKTOP_RECEIPT_QUERY).matches;
}

function getServerDesktopReceiptPaneSnapshot() {
  return false;
}

function QueryPrefill({ setInput }: { setInput: (v: string) => void }) {
  const searchParams = useSearchParams();
  useEffect(() => {
    const q = searchParams.get("q");
    if (q) setInput(q);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}

function WorkspaceInner() {
  const [receiptSelection, setReceiptSelection] = useState<ReceiptSelection | null>(null);
  const [receiptPaneWidth, setReceiptPaneWidth] = useState(DEFAULT_RECEIPT_PANE_WIDTH);
  const [isResizingReceipt, setIsResizingReceipt] = useState(false);
  const viewportWidth = useSyncExternalStore(subscribeViewport, getViewportWidth, getServerViewportWidth);
  const isDesktopReceiptPane = useSyncExternalStore(
    subscribeDesktopReceiptPane,
    getDesktopReceiptPaneSnapshot,
    getServerDesktopReceiptPaneSnapshot,
  );
  const clampedReceiptPaneWidth = clampReceiptPaneWidth(receiptPaneWidth, viewportWidth);
  const {
    threads,
    activeThread,
    messages,
    statusHistory,
    citedCountLabel,
    input,
    reasoningOpen,
    isLoading,
    error,
    status,
    setInput,
    setReasoningOpen,
    newThread,
    selectThread,
    submitQuery,
    stopQuery,
  } = useResearchThreads();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await submitQuery(input);
  };

  const openReceipt = useCallback((citation: Citation, evidenceIndex: number, opener: HTMLElement) => {
    setReceiptSelection({ citation, evidenceIndex, opener });
  }, []);

  const closeReceipt = useCallback(() => {
    const opener = receiptSelection?.opener;
    setReceiptSelection(null);
    window.requestAnimationFrame(() => opener?.focus());
  }, [receiptSelection]);

  useEffect(() => {
    const storedWidth = Number.parseInt(window.localStorage.getItem(RECEIPT_WIDTH_STORAGE_KEY) ?? "", 10);
    if (!Number.isFinite(storedWidth)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the user's last committed pane size after mount.
    setReceiptPaneWidth(clampReceiptPaneWidth(storedWidth, window.innerWidth));
  }, []);

  const resizeReceiptPane = useCallback((width: number, commit: boolean) => {
    setReceiptPaneWidth(width);
    if (commit) window.localStorage.setItem(RECEIPT_WIDTH_STORAGE_KEY, String(width));
  }, []);

  // Esc barges in on a running turn, the same gesture as an agent CLI.
  useEffect(() => {
    if (!isLoading || receiptSelection) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") stopQuery();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isLoading, receiptSelection, stopQuery]);

  return (
    <div className={`h-dvh overflow-hidden bg-(--canvas) text-(--text) ${isResizingReceipt ? "is-resizing-receipt" : ""}`}>
      <Suspense>
        <QueryPrefill setInput={setInput} />
      </Suspense>
      <div
        className={`chamber-grid-app grid h-full grid-cols-1 ${receiptSelection ? "receipt-open" : ""}`}
        style={receiptSelection ? ({ "--receipt-pane-width": `${clampedReceiptPaneWidth}px` } as CSSProperties) : undefined}
      >
        <ThreadSidebar
          threads={threads}
          onNewThread={newThread}
          onSelectThread={selectThread}
          switchingDisabled={false}
          userName="Siti Rahimah"
          userFirm="Tan & Partners · KL"
        />

        <main className="workspace-main flex min-h-0 min-w-0 flex-col bg-(--canvas)">
          <ConversationHeader title={activeThread?.title || "New thread"} />

          <div className="flex-1 overflow-y-auto px-4 py-6 md:px-6 lg:px-8">
            <div className="chamber-full-content flex w-full flex-col gap-6">
              {messages.length === 0 && <EmptyState onQuery={setInput} />}

              {messages.map((msg, i) => {
                const isAssistant = msg.role === "assistant";
                const isTail = i === messages.length - 1;

                return (
                  <div key={msg.id} className="space-y-3">
                    {isAssistant ? (
                      <AssistantMessage
                        message={msg}
                        citedCountLabel={citedCountLabel}
                        status={status}
                        isLoading={isLoading}
                        isTail={isTail}
                        reasoningOpen={reasoningOpen}
                        onToggleReasoning={() => setReasoningOpen((open) => !open)}
                        statusHistory={statusHistory}
                        onOpenReceipt={openReceipt}
                      />
                    ) : (
                      <UserMessage message={msg} />
                    )}

                    {error && isTail && (
                      <div className="rounded-xl border border-(--accent-line) bg-(--danger-soft) px-4 py-3 text-sm text-(--danger)" role="alert">
                        {error}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <Composer input={input} onInput={setInput} onSubmit={handleSubmit} onStop={stopQuery} isLoading={isLoading} />
        </main>

        {receiptSelection && (
          <>
            <ReceiptPaneResizer
              width={clampedReceiptPaneWidth}
              viewportWidth={viewportWidth}
              onResize={resizeReceiptPane}
              onDraggingChange={setIsResizingReceipt}
            />
            <CitationReceiptViewer
              key={`${receiptSelection.citation.receipt?.document_id}:${receiptSelection.citation.section_number}:${receiptSelection.evidenceIndex}`}
              citation={receiptSelection.citation}
              initialEvidenceIndex={receiptSelection.evidenceIndex}
              modal={!isDesktopReceiptPane}
              onClose={closeReceipt}
            />
          </>
        )}
      </div>
    </div>
  );
}

export default function Workspace() {
  return <WorkspaceInner />;
}
