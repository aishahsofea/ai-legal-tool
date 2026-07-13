import { useCallback, useEffect, useRef, useState } from "react";
import { cancelQuery, streamQuery, type Citation } from "@/lib/queryTransport";

export { type Citation, type Message } from "@/lib/queryTransport";

export interface QueryState {
  status: string;
  response: string;
  citations: Citation[];
  isLoading: boolean;
  error: string | null;
}

export function useQuery() {
  const [state, setState] = useState<QueryState>({
    status: "",
    response: "",
    citations: [],
    isLoading: false,
    error: null,
  });
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
    setState((s) => ({ ...s, isLoading: false, status: "" }));
  }, []);

  const submit = useCallback(async (query: string, threadId: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ status: "Connecting...", response: "", citations: [], isLoading: true, error: null });

    try {
      for await (const event of streamQuery(query, threadId, controller.signal)) {
        if (event.type === "status") {
          setState((s) => ({ ...s, status: event.message }));
        } else if (event.type === "tool_call") {
          // Surface each retrieval tool call as a PROCESS step. Routing it through
          // `status` lets it flow into statusHistory like any other step, so the
          // panel shows the agent's search actions without a schema change.
          setState((s) => ({ ...s, status: event.summary || event.name }));
        } else if (event.type === "response") {
          setState((s) => ({
            ...s,
            response: event.content,
            citations: event.citations,
            status: "",
          }));
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
  }, []);

  return { ...state, submit, cancel };
}
