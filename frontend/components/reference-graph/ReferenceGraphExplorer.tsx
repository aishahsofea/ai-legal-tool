"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Core, CytoscapeOptions, EventObjectNode, Position } from "cytoscape";
import {
  fetchComparison,
  fetchNeighborhood,
  fetchSnapshots,
  type ComparisonEdgeStatus,
  type GraphComparison,
  type GraphEdge,
  type GraphNode,
  type GraphSnapshot,
  type LogicalReference,
  type Neighborhood,
} from "@/lib/referenceGraphTransport";
import { receiptPdfUrl } from "@/lib/receiptTransport";
import { serializeReferenceGraphState } from "@/lib/referenceGraphRoute";

export type GraphLayout = "explore" | "trace";
export type GraphView = "base" | "compare" | "overlay";

export type GraphRouteState = {
  documentId: string;
  compareDocumentId: string;
  focusProvisionId: string;
  layout: GraphLayout;
  view: GraphView;
};

type DisplayNode = {
  provision_id: string;
  label: string;
  presence: "base" | "compare" | "both" | "boundary";
};

function graphMessage(status: Neighborhood["status"] | GraphComparison["status"]) {
  if (status === "not_indexed") return "Reference graph not yet indexed for this snapshot.";
  if (status === "not_indexed_base") return "Reference graph not yet indexed for the base snapshot.";
  if (status === "not_indexed_compare") return "Reference graph not yet indexed for the comparison snapshot.";
  if (status === "flag-off") return "Reference graph is currently unavailable.";
  if (status === "provision_not_found" || status === "focus_missing_base") return "The requested provision is not in the base snapshot’s reference graph.";
  if (status === "focus_missing_compare") return "The requested provision is not in the comparison snapshot’s reference graph.";
  if (status === "comparison_disabled") return "Snapshot comparison is disabled; the base graph remains independently available.";
  return "Reference graph is temporarily unavailable.";
}

function shortId(value: string) {
  return value.replace(/^act:\d+\//, "").replaceAll("/", " · ");
}

function snapshotLabel(snapshot: GraphSnapshot) {
  return `Observed ${snapshot.snapshot_date} · ${snapshot.snapshot_type}`;
}

export function fixedPresetPositions(
  nodeIds: string[],
  focus: string,
  layout: GraphLayout,
  references: Array<{ source: string; target: string }>,
): Record<string, Position> {
  const ids = [...new Set(nodeIds)].sort();
  const result: Record<string, Position> = {};
  if (ids.includes(focus)) result[focus] = { x: 0, y: 0 };
  const others = ids.filter((id) => id !== focus);
  if (layout === "explore") {
    const radius = Math.max(180, others.length * 24);
    others.forEach((id, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(others.length, 1) - Math.PI / 2;
      result[id] = { x: Math.round(Math.cos(angle) * radius), y: Math.round(Math.sin(angle) * radius) };
    });
    return result;
  }
  const incoming = new Set(references.filter((edge) => edge.target === focus).map((edge) => edge.source));
  const outgoing = new Set(references.filter((edge) => edge.source === focus).map((edge) => edge.target));
  const columns = {
    incoming: others.filter((id) => incoming.has(id)),
    outgoing: others.filter((id) => outgoing.has(id) && !incoming.has(id)),
    other: others.filter((id) => !incoming.has(id) && !outgoing.has(id)),
  };
  const place = (values: string[], x: number) => values.forEach((id, index) => {
    result[id] = { x, y: (index - (values.length - 1) / 2) * 110 };
  });
  place(columns.incoming, -260);
  place(columns.outgoing, 260);
  place(columns.other, 0);
  return result;
}

function nodeFromVersion(item: GraphNode | null, fallback: string): Pick<DisplayNode, "label"> {
  return { label: item?.label ?? shortId(fallback) };
}

export function ReferenceGraphExplorer({
  documentId,
  focusProvisionId,
  compareDocumentId = "",
  initialLayout = "explore",
  initialView = compareDocumentId ? "overlay" : "base",
  onStateChange,
}: {
  documentId: string;
  focusProvisionId: string;
  compareDocumentId?: string;
  initialLayout?: GraphLayout;
  initialView?: GraphView;
  onStateChange?: (state: GraphRouteState, history: "push" | "replace") => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [baseDocument, setBaseDocument] = useState(documentId);
  const [compareDocument, setCompareDocument] = useState(compareDocumentId);
  const [focus, setFocus] = useState(focusProvisionId);
  const [history, setHistory] = useState<string[]>([]);
  const [layout, setLayout] = useState<GraphLayout>(initialLayout);
  const [view, setView] = useState<GraphView>(initialView);
  const [selected, setSelected] = useState(focusProvisionId);
  const [neighborhood, setNeighborhood] = useState<Neighborhood | null>(null);
  const [comparison, setComparison] = useState<GraphComparison | null>(null);
  const [snapshots, setSnapshots] = useState<GraphSnapshot[]>([]);
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const state = useCallback((overrides: Partial<GraphRouteState> = {}): GraphRouteState => ({
    documentId: baseDocument,
    compareDocumentId: compareDocument,
    focusProvisionId: focus,
    layout,
    view,
    ...overrides,
  }), [baseDocument, compareDocument, focus, layout, view]);

  useEffect(() => {
    const controller = new AbortController();
    fetchSnapshots(controller.signal)
      .then((result) => {
        setSnapshots(result.snapshots);
        setComparisonEnabled(result.comparison_enabled);
        const normalizedBase = result.snapshots.find((snapshot) => (
          snapshot.document_id === baseDocument || snapshot.corpus_document_id === baseDocument
        ))?.document_id;
        const normalizedCompare = result.snapshots.find((snapshot) => (
          snapshot.document_id === compareDocument || snapshot.corpus_document_id === compareDocument
        ))?.document_id;
        if (normalizedBase && normalizedBase !== baseDocument) {
          setLoading(true);
          setBaseDocument(normalizedBase);
        }
        if (compareDocument && normalizedCompare && normalizedCompare !== compareDocument) {
          setLoading(true);
          setCompareDocument(normalizedCompare);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setSnapshots([]);
      });
    return () => controller.abort();
  }, [baseDocument, compareDocument]);

  useEffect(() => {
    const controller = new AbortController();
    const request = compareDocument
      ? fetchComparison(baseDocument, compareDocument, focus, controller.signal).then((result) => {
        setComparison(result);
        setNeighborhood(null);
      })
      : fetchNeighborhood(baseDocument, focus, controller.signal).then((result) => {
        setNeighborhood(result);
        setComparison(null);
      });
    request
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Reference graph could not be loaded.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [baseDocument, compareDocument, focus]);

  const display = useMemo(() => {
    const nodes: DisplayNode[] = [];
    let references: LogicalReference[] = [];
    if (comparison?.status === "available") {
      comparison.nodes?.forEach((node) => {
        if (view === "base" && !node.base_node) return;
        if (view === "compare" && !node.compare_node) return;
        const version = view === "compare" ? node.compare_node : node.base_node ?? node.compare_node;
        nodes.push({ provision_id: node.provision_id, ...nodeFromVersion(version, node.provision_id), presence: node.presence });
      });
      references = comparison.references ?? [];
    } else if (neighborhood?.status === "available") {
      neighborhood.nodes?.forEach((node) => nodes.push({
        provision_id: node.provision_id,
        label: node.label,
        presence: "base",
      }));
      references = (neighborhood.edges ?? []).map((edge) => ({
        logical_reference_id: `single:${edge.edge_id}`,
        logical_key: {
          source_provision_id: edge.source_provision_id,
          target_provision_id: edge.target_provision_id,
          reference_kind: edge.reference_kind,
          relationship: edge.relationship,
          literal_wording: edge.evidence.text,
        },
        occurrence_ordinal: 1,
        status: "unchanged",
        base_edge: edge,
        compare_edge: null,
      }));
    }
    const activeReferences = references.filter((reference) => (
      view === "base" ? Boolean(reference.base_edge)
        : view === "compare" ? Boolean(reference.compare_edge)
          : true
    ));
    const indexed = new Set(nodes.map((node) => node.provision_id));
    const boundary = [...new Set(activeReferences.flatMap((reference) => [
      reference.logical_key.source_provision_id,
      reference.logical_key.target_provision_id,
    ]))].filter((id) => !indexed.has(id));
    boundary.forEach((id) => nodes.push({
      provision_id: id,
      label: `${shortId(id)}\nNot indexed in this snapshot`,
      presence: "boundary",
    }));
    return { nodes, references, activeReferences };
  }, [comparison, neighborhood, view]);

  const unionGeometry = useMemo(() => {
    const references = comparison?.status === "available"
      ? comparison.references ?? []
      : neighborhood?.status === "available"
        ? (neighborhood.edges ?? []).map((edge) => ({
          logical_key: {
            source_provision_id: edge.source_provision_id,
            target_provision_id: edge.target_provision_id,
          },
        }))
        : [];
    const nodeIds = new Set(
      comparison?.status === "available"
        ? (comparison.nodes ?? []).map((node) => node.provision_id)
        : neighborhood?.status === "available"
          ? (neighborhood.nodes ?? []).map((node) => node.provision_id)
          : [],
    );
    const pairs = references.map((reference) => ({
      source: reference.logical_key.source_provision_id,
      target: reference.logical_key.target_provision_id,
    }));
    pairs.forEach(({ source, target }) => {
      nodeIds.add(source);
      nodeIds.add(target);
    });
    return { nodeIds: [...nodeIds], pairs };
  }, [comparison, neighborhood]);

  const positions = useMemo(() => fixedPresetPositions(
    unionGeometry.nodeIds,
    focus,
    layout,
    unionGeometry.pairs,
  ), [focus, layout, unionGeometry]);

  useEffect(() => {
    cyRef.current?.destroy();
    cyRef.current = null;
    const available = neighborhood?.status === "available" || comparison?.status === "available";
    if (!available || !containerRef.current) return;
    let cancelled = false;
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled || !containerRef.current) return;
      const edgeElements = display.activeReferences.flatMap((reference) => {
        const edge = view === "base" ? reference.base_edge
          : view === "compare" ? reference.compare_edge
            : reference.compare_edge ?? reference.base_edge;
        if (!edge) return [];
        return [{
          data: {
            id: `${reference.logical_reference_id}:${view}`,
            source: edge.source_provision_id,
            target: edge.target_provision_id,
            status: reference.status,
          },
        }];
      });
      const options: CytoscapeOptions = {
        container: containerRef.current,
        elements: [
          ...display.nodes.map((node) => ({
            data: { id: node.provision_id, label: node.label, presence: node.presence },
            position: positions[node.provision_id],
          })),
          ...edgeElements,
        ],
        layout: { name: "preset", fit: true, padding: 24 },
        style: [
          { selector: "node", style: { "background-color": "#175f59", label: "data(label)", color: "#20322f", "font-size": "10px", "text-wrap": "wrap", "text-max-width": "120px", "text-valign": "bottom", "text-margin-y": 6 } },
          { selector: "node[presence = 'base']", style: { shape: "ellipse", "border-width": 2, "border-color": "#8e4f32" } },
          { selector: "node[presence = 'compare']", style: { shape: "diamond", "border-width": 2, "border-color": "#237a62" } },
          { selector: "node[presence = 'boundary']", style: { "background-color": "#a66c3d", shape: "round-rectangle" } },
          { selector: "edge", style: { width: 2, "target-arrow-shape": "triangle", "curve-style": "bezier" } },
          { selector: "edge[status = 'added']", style: { "line-color": "#237a62", "target-arrow-color": "#237a62", "line-style": "solid" } },
          { selector: "edge[status = 'removed']", style: { "line-color": "#a14e32", "target-arrow-color": "#a14e32", "line-style": "dashed", "target-arrow-shape": "tee" } },
          { selector: "edge[status = 'unchanged']", style: { "line-color": "#66726f", "target-arrow-color": "#66726f", "line-style": "dotted" } },
        ],
      };
      const cy = (cytoscape as unknown as (config: CytoscapeOptions) => Core)(options);
      cy.on("tap", "node", (event: EventObjectNode) => setSelected(event.target.id()));
      cyRef.current = cy;
    }).catch(() => setError("Reference graph renderer could not be loaded."));
    return () => { cancelled = true; cyRef.current?.destroy(); cyRef.current = null; };
  }, [comparison, display, neighborhood, positions, view]);

  const emit = (next: Partial<GraphRouteState>, historyMode: "push" | "replace") => {
    onStateChange?.(state(next), historyMode);
  };

  const beginLoad = () => {
    setLoading(true);
    setError("");
  };

  const navigate = (nextFocus: string, pushHistory: boolean) => {
    beginLoad();
    if (pushHistory && nextFocus !== focus) setHistory((items) => [...items, focus]);
    setFocus(nextFocus);
    setSelected(nextFocus);
    emit({ focusProvisionId: nextFocus }, "push");
  };

  const focusHere = () => {
    if (display.nodes.some((node) => node.provision_id === selected)) navigate(selected, true);
  };
  const back = () => {
    if (onStateChange && typeof window !== "undefined") {
      window.history.back();
      return;
    }
    const previous = history.at(-1);
    if (!previous) return;
    setHistory((items) => items.slice(0, -1));
    beginLoad();
    setFocus(previous);
    setSelected(previous);
  };
  const changeLayout = (next: GraphLayout) => {
    setLayout(next);
    emit({ layout: next }, "replace");
  };
  const changeView = (next: GraphView) => {
    setView(next);
    emit({ view: next }, "replace");
  };
  const changeBase = (next: string) => {
    beginLoad();
    setBaseDocument(next);
    const nextCompare = next === compareDocument ? "" : compareDocument;
    if (!nextCompare) {
      setCompareDocument("");
      setView("base");
    }
    emit({ documentId: next, compareDocumentId: nextCompare, view: nextCompare ? view : "base" }, "replace");
  };
  const changeCompare = (next: string) => {
    beginLoad();
    setCompareDocument(next);
    const nextView = next ? "overlay" : "base";
    setView(nextView);
    emit({ compareDocumentId: next, view: nextView }, "replace");
  };

  const selectedReferences = display.activeReferences.filter((reference) => (
    reference.logical_key.source_provision_id === selected || reference.logical_key.target_provision_id === selected
  ));
  const selectedNode = display.nodes.find((node) => node.provision_id === selected);
  const resultStatus = compareDocument ? comparison?.status : neighborhood?.status;
  const currentState = state();

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Statutory reference graph">
      <div className="flex flex-wrap items-center gap-2 border-b border-(--line) bg-(--surface-soft) px-4 py-2">
        <button type="button" onClick={() => changeLayout("explore")} aria-pressed={layout === "explore"} className="rounded border border-(--line) px-2 py-1 text-xs">Explore</button>
        <button type="button" onClick={() => changeLayout("trace")} aria-pressed={layout === "trace"} className="rounded border border-(--line) px-2 py-1 text-xs">Trace</button>
        {compareDocument && (
          <div role="group" aria-label="Snapshot graph view" className="flex gap-1">
            {(["base", "compare", "overlay"] as GraphView[]).map((item) => (
              <button key={item} type="button" onClick={() => changeView(item)} aria-pressed={view === item} className="rounded border border-(--line) px-2 py-1 text-xs capitalize">{item}</button>
            ))}
          </div>
        )}
        <button type="button" onClick={focusHere} disabled={!selectedNode || selected === focus} className="rounded border border-(--line) px-2 py-1 text-xs disabled:opacity-40">Focus here</button>
        <button type="button" onClick={back} disabled={!onStateChange && history.length === 0} className="rounded border border-(--line) px-2 py-1 text-xs disabled:opacity-40">Back</button>
        {!onStateChange && <a href={serializeReferenceGraphState(currentState)} className="rounded border border-(--line) px-2 py-1 text-xs underline">Open larger</a>}
        <span className="ml-auto font-mono text-[10px] text-(--text-subtle)">1 hop · {shortId(focus)}</span>
      </div>
      {snapshots.length > 0 && (
        <div className="grid gap-2 border-b border-(--line) bg-(--surface) px-4 py-3 sm:grid-cols-2">
          <label className="text-xs text-(--text-muted)">
            Base observed snapshot
            <select aria-label="Base observed snapshot" value={baseDocument} onChange={(event) => changeBase(event.target.value)} className="mt-1 block w-full rounded border border-(--line) bg-(--surface) p-2 text-xs">
              {snapshots.map((snapshot) => <option key={snapshot.document_id} value={snapshot.document_id}>{snapshotLabel(snapshot)}</option>)}
            </select>
          </label>
          {(comparisonEnabled || compareDocument) && (
            <label className="text-xs text-(--text-muted)">
              Comparison observed snapshot
              <select aria-label="Comparison observed snapshot" value={compareDocument} onChange={(event) => changeCompare(event.target.value)} className="mt-1 block w-full rounded border border-(--line) bg-(--surface) p-2 text-xs">
                <option value="">No comparison</option>
                {compareDocument && !snapshots.some((snapshot) => snapshot.document_id === compareDocument) && <option value={compareDocument}>Unavailable or unaudited snapshot</option>}
                {snapshots.filter((snapshot) => snapshot.document_id !== baseDocument).map((snapshot) => <option key={snapshot.document_id} value={snapshot.document_id}>{snapshotLabel(snapshot)}</option>)}
              </select>
            </label>
          )}
          <p className="text-[11px] text-(--text-subtle) sm:col-span-2">Dates label observed source snapshots, not exact effective dates.</p>
        </div>
      )}
      {compareDocument && comparison?.status === "available" && (
        <div className="flex flex-wrap items-center gap-4 border-b border-(--line) px-4 py-2 text-xs" aria-label="Comparison legend">
          <span><span aria-hidden>＋ ━</span> Added ({comparison.counts?.added ?? 0})</span>
          <span><span aria-hidden>− ┄</span> Removed ({comparison.counts?.removed ?? 0})</span>
          <span><span aria-hidden>= ┈</span> Unchanged ({comparison.counts?.unchanged ?? 0})</span>
        </div>
      )}
      {loading && <p className="p-4 text-sm text-(--text-muted)" role="status">Loading references…</p>}
      {error && <p className="p-4 text-sm text-(--danger)" role="alert">{error}</p>}
      {!loading && !error && resultStatus !== "available" && <p className="p-4 text-sm text-(--text-muted)" role="status">{graphMessage(resultStatus ?? "graph_unavailable")}</p>}
      {!loading && resultStatus === "available" && (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(220px,1fr)_auto]">
          <div ref={containerRef} data-testid="reference-graph-canvas" className="min-h-[220px] border-b border-(--line)" />
          <aside className="max-h-64 overflow-auto p-4" aria-label="Selected reference evidence">
            <p className="font-mono text-[10px] uppercase tracking-wide text-(--text-subtle)">{selectedNode?.label ?? (selected ? "Not indexed" : "Select a provision")}</p>
            {selectedReferences.length === 0 && <p className="mt-2 text-sm text-(--text-muted)">No direct references.</p>}
            {selectedReferences.map((reference) => (
              <ComparisonEvidence
                key={reference.logical_reference_id}
                reference={reference}
                baseDocumentId={baseDocument}
                compareDocumentId={compareDocument}
                view={view}
              />
            ))}
          </aside>
        </div>
      )}
    </section>
  );
}

function EvidenceBlock({ edge, documentId, label }: { edge: GraphEdge; documentId: string; label: string }) {
  const page = edge.evidence.pages[0]?.page_number;
  return (
    <div className="mt-2 border-l-2 border-(--accent) pl-2">
      <p className="font-mono text-[10px] uppercase text-(--text-subtle)">{label}</p>
      <blockquote className="mt-1 text-(--text-muted)">“{edge.evidence.text}”</blockquote>
      {page && <a href={`${receiptPdfUrl(documentId)}#page=${page}`} className="mt-1 inline-block text-xs underline">Open {label.toLowerCase()} receipt page {page}</a>}
    </div>
  );
}

function ComparisonEvidence({
  reference,
  baseDocumentId,
  compareDocumentId,
  view,
}: {
  reference: LogicalReference;
  baseDocumentId: string;
  compareDocumentId: string;
  view: GraphView;
}) {
  const statusCue: Record<ComparisonEdgeStatus, string> = { added: "＋ Added", removed: "− Removed", unchanged: "= Unchanged" };
  return (
    <article className="mt-3 rounded border border-(--line) bg-(--surface) p-3 text-xs">
      <p className="font-mono text-[10px] text-(--accent)">{shortId(reference.logical_key.source_provision_id)} → {shortId(reference.logical_key.target_provision_id)}</p>
      {compareDocumentId && <p className="mt-1 font-mono text-[10px] uppercase">{statusCue[reference.status]} · occurrence {reference.occurrence_ordinal}</p>}
      {(view === "base" || view === "overlay") && reference.base_edge && <EvidenceBlock edge={reference.base_edge} documentId={baseDocumentId} label="Base" />}
      {(view === "compare" || view === "overlay") && reference.compare_edge && <EvidenceBlock edge={reference.compare_edge} documentId={compareDocumentId} label="Comparison" />}
    </article>
  );
}
