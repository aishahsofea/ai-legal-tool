import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decodeComparison,
  decodeNeighborhood,
  decodeSnapshotCatalog,
  fetchComparison,
  fetchNeighborhood,
} from "./referenceGraphTransport";

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

  it("decodes only promoted snapshot selector metadata", () => {
    expect(decodeSnapshotCatalog({
      status: "available",
      comparison_enabled: true,
      snapshots: [{
        document_id: documentId,
        corpus_document_id: "corpus",
        act_number: "265",
        act_title: "EMPLOYMENT ACT 1955",
        language: "en",
        snapshot_date: "01/02/2023",
        snapshot_type: "REPRINT ONLINE",
        source_url: "https://example.test/act.pdf",
        sha256: "a".repeat(64),
        byte_size: 100,
        page_count: 127,
        receipt_path: `/receipts/${documentId}/pdf`,
      }],
    })).toMatchObject({ status: "available", comparison_enabled: true, snapshots: [{ document_id: documentId }] });
  });

  it("keeps a disabled comparison catalog empty and independent of the base graph", () => {
    expect(decodeSnapshotCatalog({
      status: "comparison_disabled",
      comparison_enabled: false,
      snapshots: [],
    })).toEqual({
      status: "comparison_disabled",
      comparison_enabled: false,
      snapshots: [],
    });
  });

  it("keeps base and comparison evidence independent", () => {
    const graphEdge = (edgeId: string, page: number) => ({
      edge_id: edgeId,
      source_provision_id: "act:265/section:60D",
      target_provision_id: "act:265/section:4",
      relationship: "explicit_reference",
      reference_kind: "section",
      evidence: { text: "section 4", start_offset: 10, end_offset: 19, pages: [{ page_number: page, rectangles: [] }] },
    });
    const result = decodeComparison({
      status: "available",
      base_document_id: documentId,
      compare_document_id: "compare",
      focus_provision_id: "act:265/section:60D",
      counts: { added: 0, removed: 0, unchanged: 1 },
      nodes: [],
      references: [{
        logical_reference_id: "logical:1",
        logical_key: {
          source_provision_id: "act:265/section:60D",
          target_provision_id: "act:265/section:4",
          reference_kind: "section",
          relationship: "explicit_reference",
          literal_wording: "section 4",
        },
        occurrence_ordinal: 1,
        status: "unchanged",
        base_edge: graphEdge("base", 60),
        compare_edge: graphEdge("compare", 55),
      }],
    }, documentId, "compare");
    expect(result.references?.[0].base_edge?.evidence.pages[0].page_number).toBe(60);
    expect(result.references?.[0].compare_edge?.evidence.pages[0].page_number).toBe(55);
  });

  it("routes exactly one comparison pair and focus", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      status: "not_indexed_compare",
      base_document_id: documentId,
      compare_document_id: "compare",
    }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await fetchComparison(documentId, "compare", "act:265/section:60D");
    const calls = fetchMock.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit | undefined]>;
    const url = String(calls[0]?.[0]);
    expect(url).toContain(`base_document_id=${documentId}`);
    expect(url).toContain("compare_document_id=compare");
    expect(url).toContain("focus_provision_id=act%3A265%2Fsection%3A60D");
  });
});
