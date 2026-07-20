import { afterEach, describe, expect, it, vi } from "vitest";
import type { Citation } from "./queryTransport";
import {
  decodeLocatorResult,
  locateReceipt,
  ReceiptApiError,
  receiptPdfUrl,
  recordReceiptFailure,
} from "./receiptTransport";

const citation: Citation = {
  act_number: "144",
  act_title: "AKTA KEMAJUAN PETROLEUM 1974",
  section_number: "3",
  pdf_url: "https://lom.agc.gov.my/official.pdf",
  page_number: 4,
  receipt: {
    document_id: "act-144-bm-sha256-" + "a".repeat(64),
    extraction_id: "extraction-sha256-fixture",
    evidence: [{ claim: "Tuntutan.", quote: "Petikan tepat" }],
  },
};

function payload() {
  return {
    status: "matched",
    fallback_page: 4,
    document: {
      document_id: citation.receipt!.document_id,
      act_number: "144",
      act_title: citation.act_title,
      language: "bm",
      timeline_date: "2026-01-01",
      timeline_type: "REPRINT",
      sha256: "a".repeat(64),
    },
    pages: [{ page_number: 4, rectangles: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.04 }] }],
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("receipt transport", () => {
  it("encodes opaque document ids in stable API URLs", () => {
    expect(receiptPdfUrl("act/with spaces")).toContain("act%2Fwith%20spaces/pdf");
  });

  it("sends exact extraction identity and validates a BM response", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(payload()), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    const result = await locateReceipt(citation, 0);

    expect(result.document.language).toBe("bm");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      evidence_quote: "Petikan tepat",
      start_page: 4,
      extraction_id: "extraction-sha256-fixture",
    });
  });

  it("fails closed on mismatched identities and unsafe rectangles", () => {
    const mismatched = payload();
    mismatched.document.document_id = "different";
    expect(() => decodeLocatorResult(mismatched, citation.receipt!.document_id)).toThrow(ReceiptApiError);

    const unsafe = payload();
    unsafe.pages[0].rectangles[0].width = 2;
    expect(() => decodeLocatorResult(unsafe, citation.receipt!.document_id)).toThrow(/unsafe highlight/);
  });

  it("keeps sanitized telemetry fail-quiet", () => {
    const fetchMock = vi.fn(() => { throw new Error("offline"); });
    vi.stubGlobal("fetch", fetchMock);

    expect(() => recordReceiptFailure(
      "locator_request_failed", citation.receipt!.document_id,
      { stage: "locate", error: new TypeError("secret quote must not be sent"), httpStatus: 503 },
    )).not.toThrow();
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toMatchObject({ event: "locator_request_failed", error_class: "TypeError", http_status: 503 });
    expect(JSON.stringify(body)).not.toContain("secret quote");
  });
});
