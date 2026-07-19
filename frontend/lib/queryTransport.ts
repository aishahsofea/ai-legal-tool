import { getUserId } from "@/lib/userIdentity";

export interface Message {
  role: "user" | "assistant";
  content: string;
}

export interface EvidenceSpan {
  claim: string;
  quote: string;
}

export interface CitationReceipt {
  document_id: string;
  evidence: EvidenceSpan[];
}

export interface Citation {
  act_number: string;
  act_title: string;
  section_number: string;
  pdf_url: string;
  page_number: number | null;
  receipt?: CitationReceipt;
}

export type QueryEvent =
  | { type: "status"; message: string }
  | { type: "tool_call"; name: string; summary: string }
  | { type: "response"; content: string; citations: Citation[]; violations: string[] }
  | { type: "interrupt"; question: string; interrupt_id: string }
  | { type: "error"; message: string }
  | { type: "done" };

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchQueryResponse(query: string, threadId: string, signal?: AbortSignal) {
  return fetch(`${API_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thread_id: threadId, user_id: getUserId() }),
    signal,
  });
}

// Answer a clarify interrupt: the value is fed back to the paused graph as
// Command(resume=value) on the same thread_id, which streams the resumed turn (ADR 0015).
async function fetchResumeResponse(threadId: string, value: string, signal?: AbortSignal) {
  return fetch(`${API_URL}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, value, user_id: getUserId() }),
    signal,
  });
}

function decodeQueryEvent(raw: string): QueryEvent | null {
  if (!raw) return null;

  let event: Record<string, unknown>;
  try {
    event = JSON.parse(raw);
  } catch {
    return null;
  }

  if (event.type === "status" && typeof event.message === "string") {
    return { type: "status", message: event.message };
  }

  if (event.type === "tool_call") {
    return {
      type: "tool_call",
      name: typeof event.name === "string" ? event.name : "",
      summary: typeof event.summary === "string" ? event.summary : "",
    };
  }

  if (event.type === "response") {
    return {
      type: "response",
      content: typeof event.content === "string" ? event.content : "",
      citations: Array.isArray(event.citations) ? (event.citations as Citation[]) : [],
      violations: Array.isArray(event.violations) ? (event.violations as string[]) : [],
    };
  }

  if (event.type === "interrupt") {
    return {
      type: "interrupt",
      question: typeof event.question === "string" ? event.question : "",
      interrupt_id: typeof event.interrupt_id === "string" ? event.interrupt_id : "",
    };
  }

  if (event.type === "error" && typeof event.message === "string") {
    return { type: "error", message: event.message };
  }

  if (event.type === "done") {
    return { type: "done" };
  }

  return null;
}

export async function* parseSseStream<T>(
  body: ReadableStream<Uint8Array>,
  decodeEvent: (raw: string) => T | null,
  signal?: AbortSignal,
): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\n\n/);
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const lines = block
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        const data = lines
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6).trim())
          .join("\n");
        const event = decodeEvent(data);
        if (event) yield event;
      }
    }

    if (buffer.trim()) {
      const lines = buffer
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const data = lines
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6).trim())
        .join("\n");
      const event = decodeEvent(data);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

async function* streamFromResponse(res: Response, signal?: AbortSignal): AsyncGenerator<QueryEvent> {
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!res.body) {
    throw new Error("No response body");
  }
  yield* parseSseStream(res.body, decodeQueryEvent, signal);
}

export async function* streamQuery(
  query: string,
  threadId: string,
  signal?: AbortSignal,
): AsyncGenerator<QueryEvent> {
  yield* streamFromResponse(await fetchQueryResponse(query, threadId, signal), signal);
}

// Resume a turn paused at a clarify interrupt (ADR 0015). Streams the continuation —
// the resolved turn's real response — just like streamQuery.
export async function* streamResume(
  threadId: string,
  value: string,
  signal?: AbortSignal,
): AsyncGenerator<QueryEvent> {
  yield* streamFromResponse(await fetchResumeResponse(threadId, value, signal), signal);
}

// Barge-in: tell the server to stop the in-flight turn (server-authoritative, in
// case the client's fetch abort is slow to propagate). Fire-and-forget and
// fail-quiet — a failed cancel must never surface over an already-"stopped" UI.
export async function cancelQuery(threadId: string): Promise<void> {
  try {
    await fetch(`${API_URL}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId }),
      keepalive: true,
    });
  } catch {
    /* stop is best-effort; the aborted fetch already halted the client */
  }
}
