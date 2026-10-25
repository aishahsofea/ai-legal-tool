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
import { useRouter, useSearchParams } from "next/navigation";
import {
  Composer,
  ConversationHeader,
  EmptyState,
  AssistantMessage,
  ThreadLoader,
  ThreadSidebar,
  UserMessage,
} from "@/components/conversation";
import { withQuery } from "@/lib/pendingQuery";
import { useResearchThreads } from "@/lib/useResearchThreads";
import { useSession } from "@/lib/useSession";
import { useSidebarCollapsed } from "@/lib/useSidebarCollapsed";
import { getSupabase } from "@/lib/supabaseClient";
import type { Session } from "@supabase/supabase-js";
import type { Citation } from "@/lib/useQuery";
import {
  DEFAULT_RECEIPT_PANE_WIDTH,
  WORKSPACE_SIDEBAR_WIDTH,
  ReceiptPaneResizer,
  clampReceiptPaneWidth,
} from "@/components/locus-workspace/ReceiptPaneResizer";
import { SidebarResizeHandle, clampSidebarWidth } from "@/components/locus-workspace/SidebarResizeHandle";

const CitationReceiptViewer = dynamic(
  () => import("@/components/locus-workspace/CitationReceiptViewer").then((module) => module.CitationReceiptViewer),
  { ssr: false },
);

type ReceiptSelection = {
  citation: Citation;
  evidenceIndex: number;
  opener: HTMLElement;
};

const PHONE_MAX_WIDTH = 768;
const DESKTOP_RECEIPT_QUERY = "(min-width: 1200px)";
const RECEIPT_WIDTH_STORAGE_KEY = "locus.receipt-pane-width.v1";
const SIDEBAR_WIDTH_STORAGE_KEY = "locus.sidebar-width.v1";

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

function accountLabels(session: Session) {
  const { email, user_metadata: meta } = session.user;
  const name = (meta?.full_name ?? meta?.name ?? meta?.user_name) as string | undefined;
  return name ? { name, subtitle: email } : { name: email ?? "Signed in", subtitle: undefined };
}

function WorkspaceInner({ session }: { session: Session }) {
  const [receiptSelection, setReceiptSelection] = useState<ReceiptSelection | null>(null);
  const [receiptPaneWidth, setReceiptPaneWidth] = useState(DEFAULT_RECEIPT_PANE_WIDTH);
  const [isResizingReceipt, setIsResizingReceipt] = useState(false);
  const [isDraggingSidebar, setIsDraggingSidebar] = useState(false);
  const [sidebarPaneWidth, setSidebarPaneWidth] = useState(WORKSPACE_SIDEBAR_WIDTH);
  const viewportWidth = useSyncExternalStore(subscribeViewport, getViewportWidth, getServerViewportWidth);
  const isDesktopReceiptPane = useSyncExternalStore(
    subscribeDesktopReceiptPane,
    getDesktopReceiptPaneSnapshot,
    getServerDesktopReceiptPaneSnapshot,
  );
  const account = accountLabels(session);
  const [sidebarCollapsed, , setSidebarCollapsed] = useSidebarCollapsed();
  const [phoneDrawerOpen, setPhoneDrawerOpen] = useState(false);
  const isPhone = viewportWidth < PHONE_MAX_WIDTH;
  const sidebarWidth = sidebarCollapsed ? 0 : sidebarPaneWidth;
  const clampedReceiptPaneWidth = clampReceiptPaneWidth(receiptPaneWidth, viewportWidth, sidebarWidth);
  const {
    threads,
    activeThread,
    loadingThread,
    loadingThreadId,
    pendingThreadId,
    threadListStatus,
    messages,
    statusHistory,
    nodeRuns,
    citedCountLabel,
    input,
    reasoningOpen,
    isLoading,
    error,
    loadError,
    sessionEnded,
    lastUserQuery,
    status,
    setInput,
    setReasoningOpen,
    newThread,
    selectThread,
    deleteThread,
    submitQuery,
    stopQuery,
  } = useResearchThreads();

  const router = useRouter();

  // scope "local" clears the stored session without a server call, so /login doesn't bounce back here.
  const signInAgain = async () => {
    const q = input.trim() || lastUserQuery;
    // Workspace redirects to /login on signOut using the URL's q, so put the query there first.
    window.history.replaceState(null, "", withQuery("/workspace", q));
    await getSupabase().auth.signOut({ scope: "local" });
    router.replace(withQuery("/login", q));
  };

  const signOut = () => void getSupabase().auth.signOut();

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

  useEffect(() => {
    const storedWidth = Number.parseInt(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY) ?? "", 10);
    if (!Number.isFinite(storedWidth)) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the user's last committed sidebar size after mount.
    setSidebarPaneWidth(clampSidebarWidth(storedWidth));
  }, []);

  const resizeSidebar = useCallback((width: number, commit: boolean) => {
    setSidebarPaneWidth(width);
    if (commit) window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(width));
  }, []);

  // A drag-to-collapse leaves the width near MIN, so reopening always starts from the default.
  const changeSidebarCollapsed = useCallback(
    (next: boolean) => {
      if (!next && sidebarCollapsed) resizeSidebar(WORKSPACE_SIDEBAR_WIDTH, true);
      setSidebarCollapsed(next);
    },
    [sidebarCollapsed, resizeSidebar, setSidebarCollapsed],
  );

  const toggleSidebarCollapsed = useCallback(
    () => changeSidebarCollapsed(!sidebarCollapsed),
    [sidebarCollapsed, changeSidebarCollapsed],
  );

  const toggleSidebar = useCallback(
    () => (isPhone ? setPhoneDrawerOpen((open) => !open) : toggleSidebarCollapsed()),
    [isPhone, toggleSidebarCollapsed],
  );

  const startNewThread = () => {
    setPhoneDrawerOpen(false);
    newThread();
  };

  const chooseThread = (threadId: string) => {
    setPhoneDrawerOpen(false);
    return selectThread(threadId);
  };

  useEffect(() => {
    if (!phoneDrawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPhoneDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phoneDrawerOpen]);

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
    <div className={`h-dvh overflow-hidden bg-(--canvas) text-(--text) ${isResizingReceipt ? "is-resizing-receipt" : ""} ${isDraggingSidebar ? "is-resizing-sidebar" : ""}`}>
      <Suspense>
        <QueryPrefill setInput={setInput} />
      </Suspense>
      <div
        className={`chamber-grid-app grid h-full grid-cols-1 ${receiptSelection ? "receipt-open" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${phoneDrawerOpen ? "sidebar-drawer-open" : ""}`}
        style={{
          "--sidebar-width": `${sidebarPaneWidth}px`,
          ...(receiptSelection && { "--receipt-pane-width": `${clampedReceiptPaneWidth}px` }),
        } as CSSProperties}
      >
        <ThreadSidebar
          threads={threads}
          listStatus={threadListStatus}
          onNewThread={startNewThread}
          onSelectThread={chooseThread}
          onDeleteThread={deleteThread}
          pendingThreadId={pendingThreadId}
          switchingDisabled={false}
          userName={account.name}
          userSubtitle={account.subtitle}
          onSignOut={signOut}
        />

        {isPhone && phoneDrawerOpen && (
          <div
            data-testid="sidebar-backdrop"
            className="workspace-sidebar-backdrop"
            onClick={() => setPhoneDrawerOpen(false)}
          />
        )}

        <main className="workspace-main relative flex min-h-0 min-w-0 flex-col overflow-hidden bg-(--canvas)">
          <ConversationHeader
            title={(loadingThread ?? activeThread)?.title || "New thread"}
            messages={loadingThreadId ? [] : messages}
            sidebarCollapsed={isPhone ? !phoneDrawerOpen : sidebarCollapsed}
            onToggleSidebar={toggleSidebar}
            onSignOut={signOut}
          />
          <SidebarResizeHandle
            width={sidebarPaneWidth}
            collapsed={sidebarCollapsed}
            onResize={resizeSidebar}
            onCollapsedChange={changeSidebarCollapsed}
            onDraggingChange={setIsDraggingSidebar}
          />

          <div className="relative flex-1 overflow-y-auto px-4 py-6 md:px-6 lg:px-8">
            <div className="chamber-full-content flex w-full flex-col gap-6">
              {sessionEnded && (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-(--accent-line) bg-(--danger-soft) px-4 py-3 text-sm text-(--danger)" role="alert">
                  <span>Your session has ended.</span>
                  <button type="button" onClick={() => void signInAgain()} className="rounded-lg border border-(--accent-line) px-3 py-1 font-medium">
                    Sign in
                  </button>
                </div>
              )}

              {loadError && (
                <div className="rounded-xl border border-(--accent-line) bg-(--danger-soft) px-4 py-3 text-sm text-(--danger)" role="alert">
                  {loadError}
                </div>
              )}

              {loadingThreadId ? (
                <ThreadLoader />
              ) : (
                <>
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
                          nodeRuns={nodeRuns}
                          onOpenReceipt={openReceipt}
                        />
                      ) : (
                        <UserMessage message={msg} />
                      )}

                      {error && isTail && !sessionEnded && (
                        <div className="rounded-xl border border-(--accent-line) bg-(--danger-soft) px-4 py-3 text-sm text-(--danger)" role="alert">
                          {error}
                        </div>
                      )}
                    </div>
                  );
                })}
                </>
              )}
            </div>
          </div>

          <Composer input={input} onInput={setInput} onSubmit={handleSubmit} onStop={stopQuery} isLoading={isLoading} sendDisabled={loadingThreadId !== null} />
        </main>

        {receiptSelection && (
          <>
            <ReceiptPaneResizer
              width={clampedReceiptPaneWidth}
              viewportWidth={viewportWidth}
              sidebarWidth={sidebarWidth}
              onResize={resizeReceiptPane}
              onDraggingChange={setIsResizingReceipt}
            />
            <CitationReceiptViewer
              key={`${receiptSelection.citation.receipt?.document_id}:${receiptSelection.citation.section_number}:${receiptSelection.citation.path ?? ""}:${receiptSelection.evidenceIndex}`}
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
  const router = useRouter();
  const session = useSession();

  useEffect(() => {
    if (session === null) router.replace(withQuery("/login", new URLSearchParams(window.location.search).get("q")));
  }, [session, router]);

  return session ? <WorkspaceInner session={session} /> : null;
}
