import { describe, expect, it } from "vitest";
import { serializeReferenceGraphState } from "./referenceGraphRoute";

describe("reference graph route state", () => {
  it("serializes the complete comparison state with opaque identifiers", () => {
    const value = serializeReferenceGraphState({
      documentId: "base/id",
      compareDocumentId: "compare:id",
      focusProvisionId: "act:265/section:60D",
      layout: "trace",
      view: "overlay",
    });
    const url = new URL(value, "https://example.test");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      document_id: "base/id",
      compare_document_id: "compare:id",
      focus_provision_id: "act:265/section:60D",
      layout: "trace",
      overlay: "overlay",
    });
  });

  it("omits the comparison identity in backward-compatible single-snapshot mode", () => {
    expect(serializeReferenceGraphState({
      documentId: "base",
      compareDocumentId: "",
      focusProvisionId: "act:265/section:4",
      layout: "explore",
      view: "base",
    })).not.toContain("compare_document_id");
  });
});
