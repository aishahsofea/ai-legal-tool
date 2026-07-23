"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Core, CytoscapeOptions, EventObjectNode } from "cytoscape";
import { fetchNeighborhood, type GraphEdge, type Neighborhood } from "@/lib/referenceGraphTransport";

type Layout = "explore" | "trace";

function notIndexedMessage(status: Neighborhood["status"]) {
  if (status === "not_indexed") return "Reference graph not yet indexed for this snapshot.";
  if (status === "flag-off") return "Reference graph is currently unavailable.";
  if (status === "provision_not_found") return "The requested provision is not in this snapshot's reference graph.";
  return "Reference graph is temporarily unavailable.";
}

function shortId(value: string) {
  return value.replace("act:265/", "").replaceAll("/", " · ");
}

export function ReferenceGraphExplorer({
  documentId,
  focusProvisionId,
  initialLayout = "explore",
  onNavigation,
}: {
  documentId: string;
  focusProvisionId: string;
  initialLayout?: Layout;
  onNavigation?: (focus: string, layout: Layout) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [focus, setFocus] = useState(focusProvisionId);
  const [history, setHistory] = useState<string[]>([]);
  const [layout, setLayout] = useState<Layout>(initialLayout);
  const [selected, setSelected] = useState(focusProvisionId);
  const [result, setResult] = useState<Neighborhood | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const navigate = useCallback((nextFocus: string, pushHistory: boolean) => {
    setLoading(true);
    setError("");
    setFocus((current) => {
      if (pushHistory && current !== nextFocus) setHistory((items) => [...items, current]);
      return nextFocus;
    });
    setSelected(nextFocus);
  }, []);

  useEffect(() => {
    onNavigation?.(focus, layout);
  }, [focus, layout, onNavigation]);

  useEffect(() => {
    const controller = new AbortController();
    fetchNeighborhood(documentId, focus, controller.signal)
      .then(setResult)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Reference graph could not be loaded.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [documentId, focus]);

  useEffect(() => {
    cyRef.current?.destroy();
    cyRef.current = null;
    if (result?.status !== "available" || !containerRef.current) return;
    let cancelled = false;
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled || !containerRef.current) return;
      const indexedNodeIds = new Set((result.nodes ?? []).map((node) => node.provision_id));
      const boundaryIds = [...new Set((result.edges ?? []).flatMap((edge) => [edge.source_provision_id, edge.target_provision_id]))]
        .filter((provisionId) => !indexedNodeIds.has(provisionId));
      const options: CytoscapeOptions = {
        container: containerRef.current,
        elements: [
          ...(result.nodes ?? []).map((node) => ({ data: { id: node.provision_id, label: node.label } })),
          ...boundaryIds.map((provisionId) => ({ data: { id: provisionId, label: `${shortId(provisionId)}\nNot yet indexed`, boundary: true } })),
          ...(result.edges ?? []).map((edge) => ({ data: { id: edge.edge_id, source: edge.source_provision_id, target: edge.target_provision_id } })),
        ],
        style: [
          { selector: "node", style: { "background-color": "#175f59", label: "data(label)", color: "#20322f", "font-size": "10px", "text-wrap": "wrap", "text-max-width": "120px", "text-valign": "bottom", "text-margin-y": 6 } },
          { selector: "node[boundary]", style: { "background-color": "#a66c3d", shape: "round-rectangle" } },
          { selector: "edge", style: { width: 1.5, "line-color": "#a66c3d", "target-arrow-color": "#a66c3d", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
        ],
      };
      const cy = (cytoscape as unknown as (config: CytoscapeOptions) => Core)(options);
      cy.on("tap", "node", (event: EventObjectNode) => setSelected(event.target.id()));
      cyRef.current = cy;
      cy.layout(layout === "trace" ? { name: "breadthfirst", directed: true, padding: 24 } : { name: "cose", animate: false, padding: 24 }).run();
    }).catch(() => setError("Reference graph renderer could not be loaded."));
    return () => { cancelled = true; cyRef.current?.destroy(); cyRef.current = null; };
  }, [result, layout]);

  const selectedNode = result?.nodes?.find((node) => node.provision_id === selected);
  const selectedEdges = result?.edges?.filter((edge) => edge.source_provision_id === selected || edge.target_provision_id === selected) ?? [];
  const focusHere = () => { if (selectedNode) navigate(selectedNode.provision_id, true); };
  const back = () => {
    const previous = history.at(-1);
    if (!previous) return;
    setHistory((items) => items.slice(0, -1));
    navigate(previous, false);
  };
  const changeLayout = (next: Layout) => { setLayout(next); };

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Statutory reference graph">
      <div className="flex flex-wrap items-center gap-2 border-b border-(--line) bg-(--surface-soft) px-4 py-2">
        <button type="button" onClick={() => changeLayout("explore")} aria-pressed={layout === "explore"} className="rounded border border-(--line) px-2 py-1 text-xs">Explore</button>
        <button type="button" onClick={() => changeLayout("trace")} aria-pressed={layout === "trace"} className="rounded border border-(--line) px-2 py-1 text-xs">Trace</button>
        <button type="button" onClick={focusHere} disabled={!selectedNode || selected === focus} className="rounded border border-(--line) px-2 py-1 text-xs disabled:opacity-40">Focus here</button>
        <button type="button" onClick={back} disabled={history.length === 0} className="rounded border border-(--line) px-2 py-1 text-xs disabled:opacity-40">Back</button>
        <span className="ml-auto font-mono text-[10px] text-(--text-subtle)">1 hop · {shortId(focus)}</span>
      </div>
      {loading && <p className="p-4 text-sm text-(--text-muted)" role="status">Loading references…</p>}
      {error && <p className="p-4 text-sm text-(--danger)" role="alert">{error}</p>}
      {!loading && !error && result?.status !== "available" && <p className="p-4 text-sm text-(--text-muted)" role="status">{notIndexedMessage(result?.status ?? "graph_unavailable")}</p>}
      {!loading && result?.status === "available" && (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(220px,1fr)_auto]">
          <div ref={containerRef} data-testid="reference-graph-canvas" className="min-h-[220px] border-b border-(--line)" />
          <aside className="max-h-56 overflow-auto p-4" aria-label="Selected reference evidence">
            <p className="font-mono text-[10px] uppercase tracking-wide text-(--text-subtle)">{selectedNode?.label ?? (selected ? "Not yet indexed" : "Select a provision")}</p>
            {selectedEdges.length === 0 && <p className="mt-2 text-sm text-(--text-muted)">No direct references.</p>}
            {selectedEdges.map((edge) => <Evidence key={edge.edge_id} edge={edge} documentId={documentId} />)}
          </aside>
        </div>
      )}
    </section>
  );
}

function Evidence({ edge, documentId }: { edge: GraphEdge; documentId: string }) {
  const page = edge.evidence.pages[0]?.page_number;
  return (
    <article className="mt-3 rounded border border-(--line) bg-(--surface) p-3 text-xs">
      <p className="font-mono text-[10px] text-(--accent)">{shortId(edge.source_provision_id)} → {shortId(edge.target_provision_id)}</p>
      <blockquote className="mt-1 border-l-2 border-(--accent) pl-2 text-(--text-muted)">“{edge.evidence.text}”</blockquote>
      {page && <a href={`/receipts/${encodeURIComponent(documentId)}/pdf#page=${page}`} className="mt-2 inline-block text-xs underline">Open receipt page {page}</a>}
    </article>
  );
}
