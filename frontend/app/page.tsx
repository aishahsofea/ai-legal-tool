"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { FormEvent } from "react";
import {
  Composer,
  ConversationHeader,
  EmptyState,
  AssistantMessage,
  SourcesPanel,
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
    sources,
    activeSource,
    activeSourceIndex,
    citedCountLabel,
    assistantMessage,
    input,
    reasoningOpen,
    isLoading,
    error,
    status,
    setInput,
    setReasoningOpen,
    setActiveSourceIndex,
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

          <div className="flex-1 overflow-y-auto px-4 py-6 lg:px-20">
            <div className="mx-auto flex w-full chamber-max-content flex-col gap-6">
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

        <SourcesPanel
          label={citedCountLabel}
          activeSource={activeSource}
          assistantMessage={assistantMessage ?? undefined}
          onSelectSource={setActiveSourceIndex}
          sources={sources}
          activeSourceIndex={activeSourceIndex}
        />
      </div>
    </div>
  );
}
