"use client";

import { FormEvent } from "react";
import {
  Composer,
  ConversationHeader,
  EmptyState,
  AssistantMessage,
  ThreadSidebar,
  UserMessage,
} from "@/components/conversation";
import { useResearchThreads } from "@/lib/useResearchThreads";

export default function Home() {
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
  } = useResearchThreads();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await submitQuery(input);
  };

  return (
    <div className="min-h-screen bg-(--bg) text-(--ink)">
      <div className="grid min-h-screen grid-cols-1 chamber-grid-app">
        <ThreadSidebar
          threads={threads}
          onNewThread={newThread}
          onSelectThread={selectThread}
          switchingDisabled={false}
          userName="Siti Rahimah"
          userFirm="Tan & Partners · KL"
        />

        <main className="flex min-w-0 flex-col bg-(--bg)">
          <ConversationHeader title={activeThread?.title || "New thread"} />

          <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 xl:px-12">
            <div className="flex w-full chamber-full-content flex-col gap-6">
              {messages.length === 0 && <EmptyState onQuery={setInput} />}

              {messages.map((msg, i) => {
                const isAssistant = msg.role === "assistant";
                const isTail = i === messages.length - 1;

                return (
                  <div key={msg.id} className="space-y-2">
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

                    {error && isTail && <div className="text-xs text-(--ink-2)">{error}</div>}
                  </div>
                );
              })}
            </div>
          </div>

          <Composer input={input} onInput={setInput} onSubmit={handleSubmit} isLoading={isLoading} />
        </main>

      </div>
    </div>
  );
}
