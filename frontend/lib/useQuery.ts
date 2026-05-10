import { useCallback, useEffect, useRef, useState } from "react";
import { streamQuery, type Citation, type Message } from "@/lib/queryTransport";

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

  const submit = useCallback(async (query: string, history: Message[] = []) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ status: "Connecting...", response: "", citations: [], isLoading: true, error: null });

    try {
      for await (const event of streamQuery(query, history, controller.signal)) {
        if (event.type === "status") {
          setState((s) => ({ ...s, status: event.message }));
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

  return { ...state, submit };
}
