"use client";

import { Suspense, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  ReferenceGraphExplorer,
  type GraphRouteState,
  type GraphView,
} from "@/components/reference-graph/ReferenceGraphExplorer";
import { serializeReferenceGraphState } from "@/lib/referenceGraphRoute";

const DOCUMENT_ID = "act-265-reprint-2023-6fec2f07";
const DEFAULT_FOCUS = "act:265/section:60D";

function ReferenceGraphPageInner() {
  const params = useSearchParams();
  const documentId = params.get("document_id") || DOCUMENT_ID;
  const focus = params.get("focus_provision_id") || DEFAULT_FOCUS;
  const layout = params.get("layout") === "trace" ? "trace" : "explore";
  const compareDocumentId = params.get("compare_document_id") || "";
  const requestedView = params.get("overlay");
  const view: GraphView = compareDocumentId && (requestedView === "base" || requestedView === "compare" || requestedView === "overlay")
    ? requestedView
    : compareDocumentId ? "overlay" : "base";

  const onStateChange = useCallback((state: GraphRouteState, history: "push" | "replace") => {
    const method = history === "push" ? "pushState" : "replaceState";
    window.history[method](null, "", serializeReferenceGraphState(state));
  }, []);

  return (
    <main className="flex h-dvh min-h-0 flex-col bg-(--canvas) text-(--text)">
      <header className="border-b border-(--line) px-5 py-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-(--accent)">Employment Act 1955</p>
        <h1 className="mt-1 font-serif text-2xl font-light">Statutory reference graph</h1>
      </header>
      <ReferenceGraphExplorer
        key={`${documentId}:${compareDocumentId}:${focus}:${layout}:${view}`}
        documentId={documentId}
        compareDocumentId={compareDocumentId}
        focusProvisionId={focus}
        initialLayout={layout}
        initialView={view}
        onStateChange={onStateChange}
      />
    </main>
  );
}

export default function ReferenceGraphPage() {
  return <Suspense><ReferenceGraphPageInner /></Suspense>;
}
