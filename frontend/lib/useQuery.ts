import { useState, useCallback } from "react";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface Citation {
  act_number: string;
  act_title: string;
  section_number: string;
  pdf_url: string;
  page_number: number | null;
}

export interface QueryState {
  status: string;
  response: string;
  citations: Citation[];
  isLoading: boolean;
  error: string | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function useQuery() {
  const [state, setState] = useState<QueryState>({
    status: "",
    response: "",
    citations: [],
    isLoading: false,
    error: null,
  });

  const submit = useCallback(async (query: string, history: Message[] = []) => {
    setState({ status: "Connecting...", response: "", citations: [], isLoading: true, error: null });

    try {
      const res = await fetch(`${API_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, history }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: Record<string, unknown>;
          try { event = JSON.parse(raw); } catch { continue; }

          if (event.type === "status") {
            setState(s => ({ ...s, status: event.message as string }));
          } else if (event.type === "response") {
            setState(s => ({
              ...s,
              response:  event.content as string,
              citations: event.citations as Citation[],
              status:    "",
            }));
          } else if (event.type === "error") {
            setState(s => ({ ...s, error: event.message as string, status: "", isLoading: false }));
            return;
          } else if (event.type === "done") {
            setState(s => ({ ...s, isLoading: false, status: "" }));
            return;
          }
        }
      }
    } catch (err) {
      setState(s => ({
        ...s,
        error: err instanceof Error ? err.message : "Unknown error",
        isLoading: false,
        status: "",
      }));
    }
  }, []);

  return { ...state, submit };
}
