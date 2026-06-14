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

export type QueryEvent =
  | { type: "status"; message: string }
  | { type: "response"; content: string; citations: Citation[]; violations: string[] }
  | { type: "error"; message: string }
  | { type: "done" };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchQueryResponse(query: string, threadId: string, signal?: AbortSignal) {
  return fetch(`${API_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thread_id: threadId }),
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

  if (event.type === "response") {
    return {
      type: "response",
      content: typeof event.content === "string" ? event.content : "",
      citations: Array.isArray(event.citations) ? (event.citations as Citation[]) : [],
      violations: Array.isArray(event.violations) ? (event.violations as string[]) : [],
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

async function* parseSseStream(body: ReadableStream<Uint8Array>, signal?: AbortSignal): AsyncGenerator<QueryEvent> {
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
        const event = decodeQueryEvent(data);
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
      const event = decodeQueryEvent(data);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamQuery(
  query: string,
  threadId: string,
  signal?: AbortSignal,
): AsyncGenerator<QueryEvent> {
  const res = await fetchQueryResponse(query, threadId, signal);

  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!res.body) {
    throw new Error("No response body");
  }

  yield* parseSseStream(res.body, signal);
}
