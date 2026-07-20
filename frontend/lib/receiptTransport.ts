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
  language: string;
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

export class ReceiptApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "ReceiptApiError";
  }
}

export function receiptPdfUrl(documentId: string) {
  return `${API_URL}/receipts/${encodeURIComponent(documentId)}/pdf`;
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function finiteUnit(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

export function decodeLocatorResult(value: unknown, expectedDocumentId: string): LocatorResult {
  if (!record(value)) throw new ReceiptApiError("Receipt API returned malformed location data.");
  const { status, fallback_page: fallbackPage, document, pages } = value;
  if (status !== "matched" && status !== "not_found" && status !== "ambiguous") {
    throw new ReceiptApiError("Receipt API returned an invalid locator status.");
  }
  if (!positiveInteger(fallbackPage) || !record(document) || document.document_id !== expectedDocumentId) {
    throw new ReceiptApiError("Receipt API returned mismatched document identity.");
  }
  const stringFields = ["act_number", "act_title", "language", "timeline_date", "timeline_type", "sha256"];
  if (stringFields.some((field) => typeof document[field] !== "string") || !Array.isArray(pages)) {
    throw new ReceiptApiError("Receipt API returned malformed document metadata.");
  }
  const decodedPages: LocatedReceiptPage[] = pages.map((page) => {
    if (!record(page) || !positiveInteger(page.page_number) || !Array.isArray(page.rectangles)) {
      throw new ReceiptApiError("Receipt API returned malformed page coordinates.");
    }
    const rectangles: ReceiptRectangle[] = page.rectangles.map((rectangle) => {
      if (
        !record(rectangle)
        || !finiteUnit(rectangle.x)
        || !finiteUnit(rectangle.y)
        || !finiteUnit(rectangle.width)
        || !finiteUnit(rectangle.height)
        || rectangle.width <= 0
        || rectangle.height <= 0
        || rectangle.x + rectangle.width > 1.000001
        || rectangle.y + rectangle.height > 1.000001
      ) {
        throw new ReceiptApiError("Receipt API returned unsafe highlight coordinates.");
      }
      return { x: rectangle.x, y: rectangle.y, width: rectangle.width, height: rectangle.height };
    });
    return { page_number: page.page_number, rectangles };
  });
  if ((status === "matched" && (decodedPages.length === 0 || decodedPages.some((page) => page.rectangles.length === 0)))
      || (status !== "matched" && decodedPages.length !== 0)) {
    throw new ReceiptApiError("Receipt API returned inconsistent locator geometry.");
  }
  return {
    status,
    fallback_page: fallbackPage,
    document: {
      document_id: expectedDocumentId,
      act_number: document.act_number as string,
      act_title: document.act_title as string,
      language: document.language as string,
      timeline_date: document.timeline_date as string,
      timeline_type: document.timeline_type as string,
      sha256: document.sha256 as string,
    },
    pages: decodedPages,
  };
}

export async function locateReceipt(
  citation: Citation,
  evidenceIndex: number,
  signal?: AbortSignal,
): Promise<LocatorResult> {
  if (!citation.receipt) throw new ReceiptApiError("This citation has no Receipt Document.");
  const evidence = citation.receipt.evidence[evidenceIndex];
  const response = await fetch(
    `${API_URL}/receipts/${encodeURIComponent(citation.receipt.document_id)}/locate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        evidence_quote: evidence?.quote ?? null,
        start_page: citation.page_number ?? 1,
        extraction_id: citation.receipt.extraction_id ?? null,
      }),
      signal,
    },
  );
  if (!response.ok) throw new ReceiptApiError(`Receipt API returned HTTP ${response.status}.`, response.status);
  return decodeLocatorResult(await response.json(), citation.receipt.document_id);
}

export type ReceiptFailureEvent =
  | "locator_request_failed"
  | "pdf_document_load_failed"
  | "pdf_page_render_failed"
  | "receipt_integrity_rejected";

export function recordReceiptFailure(
  event: ReceiptFailureEvent,
  documentId: string,
  options: { stage?: string; error?: unknown; httpStatus?: number } = {},
): void {
  const errorClass = options.error instanceof Error ? options.error.name : typeof options.error;
  try {
    const pending = fetch(`${API_URL}/receipts/telemetry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event,
        document_id: documentId,
        stage: options.stage ?? "",
        error_class: errorClass,
        http_status: options.httpStatus ?? null,
      }),
      keepalive: true,
    });
    void Promise.resolve(pending).catch(() => undefined);
  } catch {
    // Browser telemetry must never change the receipt fallback experience.
  }
}
