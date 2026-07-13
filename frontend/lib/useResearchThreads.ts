/* eslint-disable react-hooks/set-state-in-effect -- stream events arrive through hook state and are committed into thread history here. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, type Citation } from "@/lib/useQuery";
import type { Message as ThreadMessage, ThreadSummary } from "@/components/conversation";

type ResearchThread = ThreadSummary & {
  messages: ThreadMessage[];
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

function citationKey(citation: Citation) {
  return `${citation.act_number}:${citation.section_number}`;
}

function mergeCitations(existing: Citation[], incoming: Citation[]) {
  const seen = new Set(existing.map(citationKey));
  const merged = [...existing];

  for (const citation of incoming) {
    const key = citationKey(citation);
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(citation);
    }
  }

  return merged;
}

function countUniqueSources(citations: Citation[]) {
  return new Set(citations.map((citation) => `${citation.act_number}:${citation.section_number}`)).size;
}

function summarizeSources(citations: Citation[]) {
  const citedCount = citations.length;
  const sourceCount = countUniqueSources(citations);
  return `${citedCount} citation${citedCount === 1 ? "" : "s"} · ${sourceCount} source${sourceCount === 1 ? "" : "s"}`;
}

export function useResearchThreads() {
  const [threads, setThreads] = useState<ResearchThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [pendingThreadId, setPendingThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const [activeSourceIndex, setActiveSourceIndex] = useState(0);
  const lastStatusRef = useRef<string | null>(null);
  const { submit, resume, cancel, status, response, citations, isLoading, error, pendingQuestion } = useQuery();

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) ?? null,
    [threads, activeThreadId],
  );

  const messages = activeThread?.messages ?? [];
  const statusHistory = activeThread?.statusHistory ?? [];
  const sources = activeThread?.citations ?? [];
  const activeSource = sources[activeSourceIndex] ?? null;
  const assistantMessage = [...messages].reverse().find((message) => message.role === "assistant") ?? null;
  const citedCountLabel = summarizeSources(sources);

  const syncActiveFlags = useCallback(
    (list: ResearchThread[], selectedThreadId: string | null) =>
      list.map((thread) => ({ ...thread, active: thread.id === selectedThreadId })),
    [],
  );

  const newThread = useCallback(() => {
    setInput("");
    setReasoningOpen(false);
    setActiveSourceIndex(0);
    setActiveThreadId(null);
    // Keep pendingThreadId so the in-flight answer still lands in its original thread.
    lastStatusRef.current = null;
    setThreads((prev) => syncActiveFlags(prev, null));
  }, [syncActiveFlags]);

  const selectThread = useCallback(
    (threadId: string) => {
      const selectedThread = threads.find((thread) => thread.id === threadId);
      if (!selectedThread) return;

      setActiveThreadId(threadId);
      setActiveSourceIndex(0);
      setReasoningOpen(false);
      setThreads((prev) => syncActiveFlags(prev, threadId));
    },
    [syncActiveFlags, threads],
  );

  const submitQuery = useCallback(
    async (query: string) => {
      const trimmed = query.trim();
      if (!trimmed || isLoading) return;

      const targetThreadId = activeThreadId ?? makeId();
      const selectedThread = threads.find((thread) => thread.id === targetThreadId) ?? null;
      const title = selectedThread?.title ?? deriveThreadTitle(trimmed);
      const userMessage: ThreadMessage = { id: makeId(), role: "user", content: trimmed, createdAt: nowLabel() };
      const assistantPlaceholder: ThreadMessage = { id: makeId(), role: "assistant", content: "", createdAt: nowLabel() };
      const nextMessages = [...(selectedThread?.messages ?? []), userMessage, assistantPlaceholder];

      setInput("");
      setReasoningOpen(false);
      setActiveSourceIndex(0);
      lastStatusRef.current = null;
      setActiveThreadId(targetThreadId);
      setPendingThreadId(targetThreadId);
      setThreads((prev) => {
        const exists = prev.some((thread) => thread.id === targetThreadId);
        if (!exists) {
          return syncActiveFlags(
            [
              {
                id: targetThreadId,
                title,
                meta: "Loading…",
                active: true,
                messages: nextMessages,
                citations: [],
                statusHistory: [],
              },
              ...prev,
            ],
            targetThreadId,
          );
        }

        return syncActiveFlags(
          prev.map((thread) =>
            thread.id === targetThreadId
              ? { ...thread, title, meta: "Loading…", messages: nextMessages, statusHistory: [] }
              : thread,
          ),
          targetThreadId,
        );
      });

      // The server owns conversation memory now; send only the thread id so it can
      // load and accumulate history server-side (frontend keeps its own copy for rendering).
      // While a clarify interrupt is pending, this message is the ANSWER: resume the
      // paused turn on the same thread rather than starting a new one (ADR 0015).
      if (pendingQuestion) {
        await resume(trimmed, targetThreadId);
      } else {
        await submit(trimmed, targetThreadId);
      }
    },
    [activeThreadId, isLoading, pendingQuestion, resume, submit, syncActiveFlags, threads],
  );

  // Barge-in: stop the in-flight turn on the active thread (Stop button / Esc)
  // and hand the question back to the composer so it can be edited and resent.
  // The cancelled turn wrote nothing server-side (ADR 0014), so pulling its
  // [user, empty-assistant] pair out of the transcript keeps the two in sync and
  // means a resend can't duplicate it.
  const stopQuery = useCallback(() => {
    if (!activeThreadId) return;
    cancel(activeThreadId);

    const thread = threads.find((t) => t.id === activeThreadId);
    const msgs = thread?.messages ?? [];
    const placeholder = msgs[msgs.length - 1];
    const question = msgs[msgs.length - 2];
    const isCancelledTurn =
      placeholder?.role === "assistant" && placeholder.content === "" && question?.role === "user";

    // Nothing recoverable (e.g. the answer already landed) — just leave state as is.
    if (!isCancelledTurn) return;

    setInput(question.content);
    lastStatusRef.current = null;
    setPendingThreadId(null);

    const remaining = msgs.slice(0, -2);
    if (remaining.length === 0) {
      // Barge-in on the first turn of a fresh thread: drop the empty thread and
      // return to the empty state with the question waiting in the composer.
      setThreads((prev) => syncActiveFlags(prev.filter((t) => t.id !== activeThreadId), null));
      setActiveThreadId(null);
      return;
    }

    setThreads((prev) =>
      prev.map((t) =>
        t.id === activeThreadId
          ? { ...t, messages: remaining, meta: summarizeSources(t.citations), statusHistory: [] }
          : t,
      ),
    );
  }, [activeThreadId, cancel, syncActiveFlags, threads]);

  useEffect(() => {
    if (!status || !pendingThreadId) return;
    if (lastStatusRef.current === status) return;
    lastStatusRef.current = status;

    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === pendingThreadId
          ? { ...thread, statusHistory: [...thread.statusHistory, status] }
          : thread,
      ),
    );
  }, [pendingThreadId, status]);

  useEffect(() => {
    if (!response || !pendingThreadId) return;

    setThreads((prev) =>
      prev.map((thread) => {
        if (thread.id !== pendingThreadId) {
          return { ...thread, active: thread.id === activeThreadId };
        }

        const messages = [...thread.messages];
        const last = messages[messages.length - 1];
        if (last?.role === "assistant" && last.content === "") {
          messages[messages.length - 1] = { ...last, content: response, citations };
        } else {
          messages.push({ id: makeId(), role: "assistant", content: response, createdAt: nowLabel() });
        }

        const mergedCitations = mergeCitations(thread.citations, citations);

        return {
          ...thread,
          messages,
          citations: mergedCitations,
          meta: summarizeSources(mergedCitations),
          active: thread.id === activeThreadId,
        };
      }),
    );

    if (pendingThreadId === activeThreadId) {
      setActiveSourceIndex(0);
      setReasoningOpen(false);
    }
    setPendingThreadId(null);
  }, [activeThreadId, citations, pendingThreadId, response]);

  // Clarify interrupt (ADR 0015): the graph paused to ask a question. Show it in the
  // empty assistant placeholder so the practitioner can read and answer it. pendingThreadId
  // stays set — the resumed turn's real answer lands as the next assistant message.
  useEffect(() => {
    if (!pendingQuestion || !pendingThreadId) return;

    setThreads((prev) =>
      prev.map((thread) => {
        if (thread.id !== pendingThreadId) return thread;

        const messages = [...thread.messages];
        const last = messages[messages.length - 1];
        if (last?.role === "assistant" && last.content === "") {
          messages[messages.length - 1] = { ...last, content: pendingQuestion };
        } else {
          messages.push({ id: makeId(), role: "assistant", content: pendingQuestion, createdAt: nowLabel() });
        }
        return { ...thread, messages };
      }),
    );
  }, [pendingQuestion, pendingThreadId]);

  useEffect(() => {
    if (!error) return;
    setPendingThreadId(null);
  }, [error]);

  return {
    threads,
    activeThreadId,
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
    stopQuery,
  };
}
