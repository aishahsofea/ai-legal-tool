import { API_URL, type Citation } from "@/lib/queryTransport";

export type LocatorStatus = "matched" | "not_found" | "ambiguous";

export interface ReceiptRectangle {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LocatedReceiptPage {
  page_number: number;
  rectangles: ReceiptRectangle[];
}

export interface ReceiptDocumentMetadata {
  document_id: string;
  act_number: string;
  act_title: string;
  timeline_date: string;
  timeline_type: string;
  sha256: string;
}

export interface LocatorResult {
  status: LocatorStatus;
  fallback_page: number;
  document: ReceiptDocumentMetadata;
  pages: LocatedReceiptPage[];
}

export function receiptPdfUrl(documentId: string) {
  return `${API_URL}/receipts/${encodeURIComponent(documentId)}/pdf`;
}

export async function locateReceipt(
  citation: Citation,
  evidenceIndex: number,
  signal?: AbortSignal,
): Promise<LocatorResult> {
  if (!citation.receipt) throw new Error("This citation has no Receipt Document.");
  const evidence = citation.receipt.evidence[evidenceIndex];
  const response = await fetch(
    `${API_URL}/receipts/${encodeURIComponent(citation.receipt.document_id)}/locate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        evidence_quote: evidence?.quote ?? null,
        start_page: citation.page_number ?? 1,
      }),
      signal,
    },
  );
  if (!response.ok) throw new Error(`Receipt API returned HTTP ${response.status}.`);
  return response.json() as Promise<LocatorResult>;
}
