import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeNeighborhood, fetchNeighborhood } from "./referenceGraphTransport";

const documentId = "act-265-reprint-2023-6fec2f07";

afterEach(() => vi.unstubAllGlobals());

describe("reference graph transport", () => {
  it("keeps a not-indexed snapshot explicit", () => {
    expect(decodeNeighborhood({ status: "not_indexed", document_id: documentId }, documentId)).toEqual({
      status: "not_indexed", document_id: documentId,
    });
  });

  it("routes one-hop requests with opaque identifiers", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      status: "available", document_id: documentId, focus_provision_id: "act:265/section:60D", nodes: [], edges: [],
    }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);

    await fetchNeighborhood(documentId, "act:265/section:60D");

    const calls = fetchMock.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit | undefined]>;
    expect(String(calls[0]?.[0])).toContain("document_id=act-265-reprint-2023-6fec2f07");
    expect(String(calls[0]?.[0])).toContain("focus_provision_id=act%3A265%2Fsection%3A60D");
  });
});
