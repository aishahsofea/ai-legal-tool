"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  Composer,
  ConversationHeader,
  EmptyState,
  AssistantMessage,
  SourcesPanel,
  ThreadSidebar,
  UserMessage,
  type Message,
  type ThreadSummary,
} from "@/components/conversation";
import { Citation, useQuery } from "@/lib/useQuery";

type ResearchThread = ThreadSummary & {
  messages: Message[];
  citations: Citation[];
  statusHistory: string[];
};

function nowLabel(date = new Date()) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function makeId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function deriveThreadTitle(query: string) {
  const clean = query.replace(/\s+/g, " ").trim().replace(/[?.!]+$/, "");
  const words = clean.split(" ");
  return words.length > 8 ? `${words.slice(0, 8).join(" ")}…` : clean;
}

function countUniqueSources(citations: Citation[]) {
  return new Set(citations.map((citation) => `${citation.act_number}:${citation.section_number}`)).size;
}

function summarizeSources(citations: Citation[]) {
  const citedCount = citations.length;
  const sourceCount = countUniqueSources(citations);
  return `${citedCount} citation${citedCount === 1 ? "" : "s"} · ${sourceCount} source${sourceCount === 1 ? "" : "s"}`;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [reasoningOpen, setReasoningOpen] = useState(true);
  const [activeSourceIndex, setActiveSourceIndex] = useState(0);
  const [threads, setThreads] = useState<ResearchThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [statusHistory, setStatusHistory] = useState<string[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastStatusRef = useRef<string | null>(null);
  const pendingThreadIdRef = useRef<string | null>(null);
  const { submit, status, response, citations, isLoading, error } = useQuery();

  useEffect(() => {
    if (!status) return;
    if (lastStatusRef.current === status) return;
    lastStatusRef.current = status;
    setStatusHistory((prev) => [...prev, status]);
    if (activeThreadId) {
      setThreads((prev) =>
        prev.map((thread) =>
          thread.id === activeThreadId
            ? { ...thread, statusHistory: [...thread.statusHistory, status] }
            : thread,
        ),
      );
    }
  }, [status, activeThreadId]);

  useEffect(() => {
    const pendingThreadId = pendingThreadIdRef.current;
    if (!response || !pendingThreadId) return;

    let updatedMessages: Message[] | null = null;
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last?.role === "assistant" && last.content === "") {
        updatedMessages = [...prev.slice(0, -1), { ...last, content: response, citations }];
        return updatedMessages;
      }
      updatedMessages = prev;
      return prev;
    });

    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === pendingThreadId
          ? {
              ...thread,
              messages: updatedMessages ?? thread.messages,
              citations,
              meta: summarizeSources(citations),
              active: true,
            }
          : { ...thread, active: false },
      ),
    );
    pendingThreadIdRef.current = null;
  }, [response, citations]);

  useEffect(() => {
    if (citations.length) setActiveSourceIndex(0);
  }, [citations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status, isLoading]);

  const activeThread = threads.find((thread) => thread.active) ?? null;
  const sources = activeThread?.citations ?? citations;
  const activeSource = sources[activeSourceIndex] ?? null;
  const assistantMessage = [...messages].reverse().find((message) => message.role === "assistant");
  const citedCountLabel = summarizeSources(sources);

  const handleNewThread = () => {
    setMessages([]);
    setInput("");
    setReasoningOpen(true);
    setActiveSourceIndex(0);
    setStatusHistory([]);
    lastStatusRef.current = null;
    pendingThreadIdRef.current = null;
    setActiveThreadId(null);
    setThreads((prev) => prev.map((thread) => ({ ...thread, active: false })));
  };

  const handleSelectThread = (threadId: string) => {
    if (isLoading) return;
    const selectedThread = threads.find((thread) => thread.id === threadId);
    if (!selectedThread) return;

    setActiveThreadId(threadId);
    setMessages(selectedThread.messages);
    setStatusHistory(selectedThread.statusHistory);
    setActiveSourceIndex(0);
    setReasoningOpen(true);
    lastStatusRef.current = null;
    setThreads((prev) => prev.map((thread) => ({ ...thread, active: thread.id === threadId })));
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const query = input.trim();
    if (!query || isLoading) return;

    const threadId = makeId();
    const title = deriveThreadTitle(query);
    setInput("");
    setReasoningOpen(true);
    setActiveSourceIndex(0);
    setStatusHistory([]);
    lastStatusRef.current = null;
    setActiveThreadId(threadId);
    pendingThreadIdRef.current = threadId;
    const nextMessages: Message[] = [
      { id: makeId(), role: "user", content: query, createdAt: nowLabel() },
      { id: makeId(), role: "assistant", content: "", createdAt: nowLabel() },
    ];
    setThreads((prev) => [
      { id: threadId, title, meta: "Loading…", active: true, messages: nextMessages, citations: [], statusHistory: [] },
      ...prev.map((thread) => ({ ...thread, active: false })),
    ]);
    setMessages(nextMessages);
    await submit(query);
  };

  return (
    <div className="min-h-screen bg-(--bg) text-(--ink)">
      <div className="grid min-h-screen grid-cols-1 chamber-grid-app">
        <ThreadSidebar
          threads={threads}
          onNewThread={handleNewThread}
          onSelectThread={handleSelectThread}
          switchingDisabled={isLoading}
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

              <div ref={bottomRef} />
            </div>
          </div>

          <Composer input={input} onInput={setInput} onSubmit={handleSubmit} isLoading={isLoading} />
        </main>

        <SourcesPanel
          label={citedCountLabel}
          activeSource={activeSource}
          assistantMessage={assistantMessage}
          onSelectSource={setActiveSourceIndex}
          sources={sources}
          activeSourceIndex={activeSourceIndex}
        />
      </div>
    </div>
  );
}
