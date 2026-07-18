"use client";

import { FormEvent, Suspense, useEffect } from "react";
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

  // Esc barges in on a running turn, the same gesture as an agent CLI.
  useEffect(() => {
    if (!isLoading) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") stopQuery();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isLoading, stopQuery]);

  return (
    <div className="h-dvh overflow-hidden bg-(--canvas) text-(--text)">
      <Suspense>
        <QueryPrefill setInput={setInput} />
      </Suspense>
      <div className="chamber-grid-app grid h-full grid-cols-1">
        <ThreadSidebar
          threads={threads}
          onNewThread={newThread}
          onSelectThread={selectThread}
          switchingDisabled={false}
          userName="Siti Rahimah"
          userFirm="Tan & Partners · KL"
        />

        <main className="flex min-h-0 min-w-0 flex-col bg-(--canvas)">
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
      </div>
    </div>
  );
}

export default function Workspace() {
  return <WorkspaceInner />;
}
