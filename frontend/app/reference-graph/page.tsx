"use client";

import { Suspense, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ReferenceGraphExplorer } from "@/components/reference-graph/ReferenceGraphExplorer";

const DOCUMENT_ID = "act-265-reprint-2023-6fec2f07";
const DEFAULT_FOCUS = "act:265/section:60D";

function ReferenceGraphPageInner() {
  const params = useSearchParams();
  const documentId = params.get("document_id") || DOCUMENT_ID;
  const focus = params.get("focus_provision_id") || DEFAULT_FOCUS;
  const layout = params.get("layout") === "trace" ? "trace" : "explore";
  const compareDocumentId = params.get("compare_document_id");

  const onNavigation = useCallback((nextFocus: string, nextLayout: "explore" | "trace") => {
    const next = new URLSearchParams({ document_id: documentId, focus_provision_id: nextFocus, layout: nextLayout });
    // Comparison is deliberately reserved, not implemented: retain the supplied
    // document identity without fetching a second graph.
    if (compareDocumentId) next.set("compare_document_id", compareDocumentId);
    window.history.replaceState(null, "", `/reference-graph?${next}`);
  }, [compareDocumentId, documentId]);

  return (
    <main className="flex h-dvh min-h-0 flex-col bg-(--canvas) text-(--text)">
      <header className="border-b border-(--line) px-5 py-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-(--accent)">Employment Act 1955</p>
        <h1 className="mt-1 font-serif text-2xl font-light">Statutory reference graph</h1>
      </header>
      <ReferenceGraphExplorer key={`${documentId}:${focus}:${layout}`} documentId={documentId} focusProvisionId={focus} initialLayout={layout} onNavigation={onNavigation} />
    </main>
  );
}

export default function ReferenceGraphPage() {
  return <Suspense><ReferenceGraphPageInner /></Suspense>;
}
