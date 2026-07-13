import { useCallback, useEffect, useRef, useState } from "react";
import { cancelQuery, streamQuery, streamResume, type Citation, type QueryEvent } from "@/lib/queryTransport";

export { type Citation, type Message } from "@/lib/queryTransport";

export interface QueryState {
  status: string;
  response: string;
  citations: Citation[];
  isLoading: boolean;
  error: string | null;
  // Set when the graph pauses to ask a clarifying question (ADR 0015). While non-null,
  // the next user message is the ANSWER and must be sent via resume(), not a new turn.
  pendingQuestion: string | null;
}

const IDLE: QueryState = {
  status: "",
  response: "",
  citations: [],
  isLoading: false,
  error: null,
  pendingQuestion: null,
};

export function useQuery() {
  const [state, setState] = useState<QueryState>(IDLE);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Barge-in / Esc: abort the fetch AND tell the server to stop, then clear
  // isLoading immediately so the UI feels instant. No-op when nothing is running.
  const cancel = useCallback((threadId: string) => {
    abortRef.current?.abort();
    abortRef.current = null;
    void cancelQuery(threadId);
    setState((s) => ({ ...s, isLoading: false, status: "", pendingQuestion: null }));
  }, []);

  // Shared event loop for both a fresh turn (streamQuery) and a resumed one
  // (streamResume) — they differ only in the source generator.
  const consume = useCallback(
    async (makeStream: (signal: AbortSignal) => AsyncGenerator<QueryEvent>, controller: AbortController) => {
      try {
        for await (const event of makeStream(controller.signal)) {
          if (event.type === "status") {
            setState((s) => ({ ...s, status: event.message }));
          } else if (event.type === "tool_call") {
            // Surface each retrieval tool call as a PROCESS step. Routing it through
            // `status` lets it flow into statusHistory like any other step, so the
            // panel shows the agent's search actions without a schema change.
            setState((s) => ({ ...s, status: event.summary || event.name }));
          } else if (event.type === "response") {
            setState((s) => ({ ...s, response: event.content, citations: event.citations, status: "" }));
          } else if (event.type === "interrupt") {
            // The graph paused for clarification. Drop out of loading so the composer
            // accepts the answer; useResearchThreads renders the question and routes
            // the next submit through resume().
            setState((s) => ({ ...s, pendingQuestion: event.question, status: "", isLoading: false }));
          } else if (event.type === "error") {
            setState((s) => ({ ...s, error: event.message, status: "", isLoading: false }));
            return;
          } else if (event.type === "done") {
            setState((s) => ({ ...s, isLoading: false, status: "" }));
            return;
          }
        }
        setState((s) => ({ ...s, isLoading: false, status: "" }));
      } catch (err) {
        if (controller.signal.aborted) return;
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err.message : "Unknown error",
          isLoading: false,
          status: "",
        }));
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [],
  );

  const start = useCallback(
    (makeStream: (signal: AbortSignal) => AsyncGenerator<QueryEvent>) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ ...IDLE, status: "Connecting...", isLoading: true });
      return consume(makeStream, controller);
    },
    [consume],
  );

  const submit = useCallback(
    (query: string, threadId: string) => start((signal) => streamQuery(query, threadId, signal)),
    [start],
  );

  const resume = useCallback(
    (value: string, threadId: string) => start((signal) => streamResume(threadId, value, signal)),
    [start],
  );

  return { ...state, submit, resume, cancel };
}
