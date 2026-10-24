import { describe, expect, it } from "vitest";
import type { StoredThread } from "@/lib/threadsTransport";
import thread from "./example-thread.json";
import { EXAMPLE_MESSAGES, EXAMPLE_META } from "./exampleAnswer";

const stored = thread as StoredThread;
const assistant = EXAMPLE_MESSAGES[1];

describe("example answer fixture", () => {
  it("records the thread id and the date it was produced", () => {
    expect(EXAMPLE_META.threadId).toBe(stored.id);
    expect(EXAMPLE_META.producedOn).toBe("24 Oct 2026");
  });

  it("is one user turn then one assistant turn with stable ids", () => {
    expect(EXAMPLE_MESSAGES.map((message) => [message.id, message.role])).toEqual([
      ["example-user", "user"],
      ["example-assistant", "assistant"],
    ]);
    expect(EXAMPLE_MESSAGES.every((message) => message.createdAt === EXAMPLE_META.producedOn)).toBe(true);
  });

  it("keeps role and content as captured", () => {
    EXAMPLE_MESSAGES.forEach((message, index) => {
      expect(message.role).toBe(stored.messages[index].role);
      expect(message.content).toBe(stored.messages[index].content);
    });
  });

  it("has at least 2 citations, one with a page and a full receipt", () => {
    const citations = assistant.citations ?? [];
    expect(citations.length).toBeGreaterThanOrEqual(2);
    expect(
      citations.some(
        (citation) =>
          citation.page_number != null &&
          citation.receipt?.document_id &&
          citation.receipt.extraction_id &&
          citation.receipt.evidence.length > 0,
      ),
    ).toBe(true);
  });

  it("has a superseded or repealed Currency Label", () => {
    expect(assistant.currency_labels?.some((l) => l.label === "superseded" || l.label === "repealed")).toBe(true);
  });
});
