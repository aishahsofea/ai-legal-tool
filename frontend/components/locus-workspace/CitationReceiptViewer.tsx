"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Document, Page, pdfjs } from "react-pdf";
import type { Citation } from "@/lib/useQuery";
import {
  locateReceipt,
  ReceiptApiError,
  recordReceiptFailure,
  receiptPdfUrl,
  type LocatorResult,
} from "@/lib/receiptTransport";
import { formatSourceTitle } from "./citationRefs";

const CitationReferences = dynamic(
  () => import("@/components/reference-graph/ReferenceGraphExplorer").then((module) => module.ReferenceGraphExplorer),
  { ssr: false, loading: () => <p className="p-4 text-sm text-(--text-muted)" role="status">Loading references…</p> },
);

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const MIN_ZOOM = 0.75;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.25;

function useContainerWidth() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    let animationFrame = 0;
    const update = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        setWidth(Math.max(280, node.clientWidth - 32));
      });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      observer.disconnect();
    };
  }, []);

  return { containerRef, width };
}

function resultMessage(result: LocatorResult | null, hasEvidence: boolean) {
  if (!result) return "";
  if (!hasEvidence) return "No verified passage was available.";
  if (result.status === "not_found") return "Exact passage could not be pinpointed.";
  if (result.status === "ambiguous") return "The passage appeared more than once, so no unique match was selected.";
  return "Verified passage located. Highlighted words match the supporting quote.";
}

export function CitationReceiptViewer({
  citation,
  initialEvidenceIndex = 0,
  modal = true,
  onClose,
}: {
  citation: Citation;
  initialEvidenceIndex?: number;
  modal?: boolean;
  onClose: () => void;
}) {
  const receipt = citation.receipt;
  const evidence = receipt?.evidence ?? [];
  const [evidenceIndex, setEvidenceIndex] = useState(() => Math.min(initialEvidenceIndex, Math.max(0, evidence.length - 1)));
  const requestKey = `${receipt?.document_id ?? "none"}:${citation.section_number}:${evidenceIndex}`;
  const [locatorState, setLocatorState] = useState<{ key: string; result: LocatorResult | null; error: string }>({ key: "", result: null, error: "" });
  const [pdfErrorState, setPdfErrorState] = useState<{ key: string; error: string }>({ key: "", error: "" });
  const [pageNumber, setPageNumber] = useState(citation.page_number ?? 1);
  const [pageCount, setPageCount] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [inspectorTab, setInspectorTab] = useState<"receipt" | "references">("receipt");
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const requestSequence = useRef(0);
  const { containerRef, width } = useContainerWidth();

  const selectedEvidence = evidence[evidenceIndex];
  const locator = locatorState.key === requestKey ? locatorState.result : null;
  const locatorError = locatorState.key === requestKey ? locatorState.error : "";
  const pdfError = pdfErrorState.key === receipt?.document_id ? pdfErrorState.error : "";
  const locating = locatorState.key !== requestKey;
  const matchedPage = locator?.status === "matched"
    ? locator.pages.find((page) => page.page_number === pageNumber)
    : undefined;
  const message = resultMessage(locator, Boolean(selectedEvidence));

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onClose();
        return;
      }
      if (!modal || event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [modal, onClose]);

  useEffect(() => {
    if (!receipt) return;
    const controller = new AbortController();
    const sequence = ++requestSequence.current;

    locateReceipt(citation, evidenceIndex, controller.signal)
      .then((result) => {
        if (sequence !== requestSequence.current) return;
        setLocatorState({ key: requestKey, result, error: "" });
        setPageNumber(result.status === "matched" ? result.pages[0].page_number : result.fallback_page);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || sequence !== requestSequence.current) return;
        recordReceiptFailure("locator_request_failed", receipt.document_id, {
          stage: "locate",
          error,
          httpStatus: error instanceof ReceiptApiError ? error.status : undefined,
        });
        setLocatorState({
          key: requestKey,
          result: null,
          error: error instanceof Error ? error.message : "Citation Receipt could not be loaded.",
        });
        setPageNumber(citation.page_number ?? 1);
      });

    return () => controller.abort();
  }, [citation, evidenceIndex, receipt, requestKey]);

  const pageWidth = useMemo(() => Math.round(width * zoom), [width, zoom]);
  if (!receipt) return null;

  return (
    <div
      className="citation-receipt-layer fixed inset-0 z-50 min-h-0 min-w-0"
      data-mode={modal ? "sheet" : "pane"}
      data-testid="receipt-layer"
      aria-live="off"
    >
      {modal && (
        <button
          type="button"
          className="citation-receipt-backdrop"
          aria-label="Close Citation Receipt"
          onClick={onClose}
        />
      )}
      <aside
        id="citation-receipt-pane"
        ref={dialogRef}
        role="dialog"
        aria-modal={modal ? true : undefined}
        aria-labelledby="citation-receipt-title"
        className="citation-receipt-panel absolute inset-y-0 right-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden border-l border-(--line) bg-(--canvas) shadow-2xl motion-reduce:transition-none lg:w-[min(54vw,800px)]"
      >
        <header className="shrink-0 border-b border-(--line) bg-(--surface) px-4 py-3 sm:px-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-(--accent)">Source used for this answer</p>
              <h2 id="citation-receipt-title" className="mt-1 font-serif text-xl font-light text-(--text)">
                {formatSourceTitle(citation.act_title)}
              </h2>
              <p className="mt-1 text-xs text-(--text-muted)">
                Act {citation.act_number} · Section {citation.section_number}
                {locator ? ` · ${locator.document.timeline_type}, ${locator.document.timeline_date}` : ""}
                {locator ? ` · ${locator.document.language === "bm" ? "Bahasa Malaysia" : "English"}` : ""}
              </p>
            </div>
            <button ref={closeRef} type="button" onClick={onClose} aria-label="Close Citation Receipt" className="min-h-8 shrink-0 whitespace-nowrap rounded-lg border border-(--line) bg-(--surface) px-3 py-1 text-xs leading-4 text-(--text-muted) hover:text-(--accent)">
              Close
            </button>
          </div>

          {evidence.length > 1 && (
            <div className="mt-3 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Verified evidence passages">
              {evidence.map((span, index) => (
                <button
                  key={`${span.claim}-${index}`}
                  type="button"
                  aria-pressed={index === evidenceIndex}
                  onClick={() => setEvidenceIndex(index)}
                  className={`min-h-8 shrink-0 whitespace-nowrap rounded-full border px-3 py-1 font-mono text-[10px] leading-4 uppercase tracking-wide ${index === evidenceIndex ? "border-(--accent) bg-(--accent-soft) text-(--accent)" : "border-(--line) bg-(--surface) text-(--text-muted)"}`}
                >
                  Evidence {index + 1}
                </button>
              ))}
            </div>
          )}

          {selectedEvidence && (
            <div className="mt-3 grid gap-2 rounded-lg border border-(--accent-line) bg-(--accent-tint) p-3 text-xs leading-5">
              <p><span className="font-mono text-[10px] uppercase tracking-wide text-(--text-subtle)">Claim</span><br />{selectedEvidence.claim}</p>
              <blockquote className="border-l-2 border-(--accent) pl-3 font-serif italic text-(--text-muted)">“{selectedEvidence.quote}”</blockquote>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-3">
            {citation.pdf_url && (
              <a href={citation.pdf_url} target="_blank" rel="noopener noreferrer" className="chamber-link font-mono text-[10px] uppercase tracking-[0.12em]">
                Check latest on AGC ↗
              </a>
            )}
            <span className="text-xs text-(--text-subtle)">Receipt snapshot {receipt.document_id}</span>
          </div>
          <div className="mt-3 flex gap-2" role="tablist" aria-label="Citation Inspector">
            <button type="button" role="tab" aria-selected={inspectorTab === "receipt"} onClick={() => setInspectorTab("receipt")} className={`rounded border px-3 py-1 font-mono text-[10px] uppercase tracking-wide ${inspectorTab === "receipt" ? "border-(--accent) text-(--accent)" : "border-(--line) text-(--text-muted)"}`}>Receipt</button>
            <button type="button" role="tab" aria-selected={inspectorTab === "references"} onClick={() => setInspectorTab("references")} className={`rounded border px-3 py-1 font-mono text-[10px] uppercase tracking-wide ${inspectorTab === "references" ? "border-(--accent) text-(--accent)" : "border-(--line) text-(--text-muted)"}`}>References</button>
          </div>
        </header>

        {inspectorTab === "references" ? (
          <CitationReferences
            documentId={receipt.document_id}
            focusProvisionId={`act:${citation.act_number}/section:${citation.section_number}`}
          />
        ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="shrink-0 border-b border-(--line-soft) bg-(--surface-soft) px-4 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <button type="button" aria-label="Previous PDF page" disabled={pageNumber <= 1} onClick={() => setPageNumber((page) => Math.max(1, page - 1))} className="h-8 w-8 rounded border border-(--line) bg-(--surface) p-0 text-sm leading-4 disabled:opacity-40">←</button>
                <span className="min-w-24 text-center font-mono text-[10px] uppercase tracking-wide" aria-label={`Page ${pageNumber} of ${pageCount || "unknown"}`}>Page {pageNumber} of {pageCount || "…"}</span>
                <button type="button" aria-label="Next PDF page" disabled={pageCount === 0 || pageNumber >= pageCount} onClick={() => setPageNumber((page) => Math.min(pageCount, page + 1))} className="h-8 w-8 rounded border border-(--line) bg-(--surface) p-0 text-sm leading-4 disabled:opacity-40">→</button>
              </div>
              <div className="flex items-center gap-2" role="group" aria-label="PDF zoom controls">
                <button type="button" aria-label="Zoom out" disabled={zoom <= MIN_ZOOM} onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value - ZOOM_STEP))} className="h-8 w-8 rounded border border-(--line) bg-(--surface) p-0 text-sm leading-4 disabled:opacity-40">−</button>
                <button type="button" aria-label="Reset zoom" onClick={() => setZoom(1)} className="h-8 min-w-14 rounded border border-(--line) bg-(--surface) px-2 py-1 font-mono text-[10px] leading-4">{Math.round(zoom * 100)}%</button>
                <button type="button" aria-label="Zoom in" disabled={zoom >= MAX_ZOOM} onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value + ZOOM_STEP))} className="h-8 w-8 rounded border border-(--line) bg-(--surface) p-0 text-sm leading-4 disabled:opacity-40">+</button>
              </div>
            </div>
            <p className={`mt-2 text-xs ${locatorError || pdfError ? "text-(--danger)" : "text-(--text-muted)"}`} role={locatorError || pdfError ? "alert" : "status"} aria-live="polite">
              {locating ? "Locating verified passage…" : locatorError || pdfError || message}
            </p>
          </div>

          <div
            ref={containerRef}
            className="min-h-0 flex-1 overflow-auto bg-(--surface-strong) p-4"
            data-testid="receipt-pdf-scroll"
            aria-busy={locating}
          >
            <Document
              file={receiptPdfUrl(receipt.document_id)}
              onLoadSuccess={({ numPages }) => {
                setPageCount(numPages);
                setPdfErrorState({ key: receipt.document_id, error: "" });
                setPageNumber((page) => Math.min(Math.max(1, page), numPages));
              }}
              onLoadError={(error) => {
                setPdfErrorState({ key: receipt.document_id, error: `Receipt PDF could not be rendered: ${error.message}` });
                recordReceiptFailure("pdf_document_load_failed", receipt.document_id, { stage: "document", error });
              }}
              onSourceError={(error) => {
                setPdfErrorState({ key: receipt.document_id, error: `Receipt PDF source could not be loaded: ${error.message}` });
                recordReceiptFailure("pdf_document_load_failed", receipt.document_id, { stage: "source", error });
              }}
              loading={<p className="p-6 text-center text-sm text-(--text-muted)" role="status">Loading Receipt Document…</p>}
              error={<p className="p-6 text-center text-sm text-(--danger)" role="alert">Receipt Document is unavailable.</p>}
            >
              <div className="relative mx-auto w-fit overflow-hidden bg-white shadow-xl" data-testid="receipt-pdf-page">
                <Page
                  pageNumber={pageNumber}
                  width={pageWidth}
                  renderAnnotationLayer={false}
                  renderTextLayer={false}
                  onRenderError={(error) => {
                    setPdfErrorState({ key: receipt.document_id, error: `Receipt PDF page could not be rendered: ${error.message}` });
                    recordReceiptFailure("pdf_page_render_failed", receipt.document_id, { stage: "page", error });
                  }}
                  loading={<p className="p-6 text-sm text-(--text-muted)" role="status">Rendering page…</p>}
                />
                {matchedPage && !locatorError && !pdfError && (
                  <div className="pointer-events-none absolute inset-0" aria-hidden="true">
                    {matchedPage.rectangles.map((rectangle, index) => (
                      <span
                        key={`${rectangle.x}-${rectangle.y}-${index}`}
                        data-testid="receipt-highlight"
                        className="absolute border border-amber-700/70 bg-amber-300/45 mix-blend-multiply"
                        style={{
                          left: `${rectangle.x * 100}%`,
                          top: `${rectangle.y * 100}%`,
                          width: `${rectangle.width * 100}%`,
                          height: `${rectangle.height * 100}%`,
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            </Document>
          </div>
        </div>
        )}
      </aside>
    </div>
  );
}
