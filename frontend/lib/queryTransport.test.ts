import { afterEach, describe, expect, it, vi } from "vitest";
import { streamQuery, type QueryEvent } from "./queryTransport";

function sseBody(events: Record<string, unknown>[]) {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
}

function stubFetch(events: Record<string, unknown>[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, body: sseBody(events) }) as unknown as Response),
  );
}

async function collect(events: Record<string, unknown>[]) {
  stubFetch(events);
  const out: QueryEvent[] = [];
  for await (const event of streamQuery("q", "t1")) out.push(event);
  return out;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("node events", () => {
  it("decodes name, model and duration", async () => {
    const events = await collect([
      { type: "node", name: "synthesiser", model: "nvidia/Nemotron-Super", duration_ms: 2410 },
      { type: "done" },
    ]);
    expect(events[0]).toEqual({
      type: "node",
      name: "synthesiser",
      model: "nvidia/Nemotron-Super",
      duration_ms: 2410,
    });
  });

  it("keeps every row, including a repeated node from a retry", async () => {
    const events = await collect([
      { type: "node", name: "synthesiser", model: "m", duration_ms: 10 },
      { type: "node", name: "synthesiser", model: "m", duration_ms: 12 },
      { type: "done" },
    ]);
    expect(events.filter((e) => e.type === "node")).toHaveLength(2);
  });

  it("preserves execution order alongside tool calls", async () => {
    const events = await collect([
      { type: "node", name: "router", model: "m1", duration_ms: 1 },
      { type: "tool_call", name: "search_statutes", summary: "Searching" },
      { type: "node", name: "synthesiser", model: "m2", duration_ms: 2 },
      { type: "done" },
    ]);
    expect(events.map((e) => e.type)).toEqual(["node", "tool_call", "node", "done"]);
  });

  it("substitutes defaults for missing fields rather than dropping the row", async () => {
    const events = await collect([{ type: "node" }, { type: "done" }]);
    expect(events[0]).toEqual({ type: "node", name: "", model: "", duration_ms: 0 });
  });

  it("leaves the rest of the stream unchanged", async () => {
    const events = await collect([
      { type: "status", message: "Classifying query..." },
      { type: "node", name: "router", model: "m", duration_ms: 1 },
      { type: "response", content: "answer", citations: [], violations: [] },
      { type: "done" },
    ]);
    expect(events.filter((e) => e.type !== "node")).toEqual([
      { type: "status", message: "Classifying query..." },
      { type: "response", content: "answer", citations: [], violations: [] },
      { type: "done" },
    ]);
  });
});
