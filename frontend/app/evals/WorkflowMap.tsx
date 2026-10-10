"use client";

import type { Core, CytoscapeOptions, EdgeSingular, EventObject, EventObjectEdge, EventObjectNode } from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { fetchEvalWorkflow, type EvalWorkflow, type WorkflowNode, type WorkflowNodeKind } from "@/lib/evalsTransport";
import { palette } from "./palette";
import { Select } from "./Select";

const COL = 190;
const ROW = 72;
const ZOOM_STEP = 1.25;
const NODE_WIDTH = 160;
const NODE_PAD = 6;
const FONT_PX = 10;
const LINE_PX = 13;
// Monospace glyphs are ~0.6em wide, so this many characters fit across the node; longer lines are pre-broken.
const LINE_CHARS = Math.floor((NODE_WIDTH - 2 * NODE_PAD) / (FONT_PX * 0.6));

const KIND_STYLE: Record<WorkflowNodeKind, { label: string; fill: string; stroke: string }> = {
  llm: { label: "LLM call", fill: "#dbeafe", stroke: "#2563eb" },
  deterministic: { label: "deterministic", fill: "#dcfce7", stroke: "#16a34a" },
  control: { label: "control / bookkeeping", fill: "#fef3c7", stroke: "#d97706" },
};

const EYEBROW = "font-mono text-[10px] font-bold uppercase tracking-[0.1em]";
const TOOL = "rounded-lg border px-2.5 py-1 font-mono text-xs font-semibold";

type Point = { x: number; y: number };
type LineStyle = "curved" | "right-angle";

const positionOf = (node: WorkflowNode): Point => ({ x: node.lane * COL, y: node.rank * ROW });
const shortModel = (model: string) => model.split("/").pop() ?? model;
// One model per line so a call chain never runs past the box; height grows with the line count.
export function nodeLabel(node: WorkflowNode): { label: string; height: number } {
  const lines = [node.id, ...node.models.map((model, i) => `${i ? "→ " : ""}${shortModel(model)}`)]
    .flatMap((line) => line.match(new RegExp(`.{1,${LINE_CHARS}}`, "g")) ?? [line]);
  return { label: lines.join("\n"), height: Math.max(38, lines.length * LINE_PX + 2 * NODE_PAD) };
}
const runnableSet = (node: WorkflowNode) => node.evals.find((entry) => entry.set)?.set;

type Bend = { distance: number; weight: number };

// Cytoscape places an unbundled-bezier control point as a weight along source→target plus a perpendicular distance.
function bendAt(source: Point, target: Point, control: Point): Bend {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.hypot(dx, dy) || 1;
  const cx = control.x - source.x;
  const cy = control.y - source.y;
  return { weight: (cx * dx + cy * dy) / length ** 2, distance: (dx * cy - dy * cx) / length };
}

// Long cross-lane edges bend at the source's lane and the target's row, so they run beside the spine instead of through nodes.
export function edgeBend(source: Point, target: Point): Bend {
  if (source.x === target.x) return { distance: 0, weight: 0.5 };
  if (Math.abs(target.y - source.y) > ROW) return bendAt(source, target, { x: source.x, y: target.y });
  return { distance: 0.15 * Math.hypot(target.x - source.x, target.y - source.y), weight: 0.5 };
}

// The control point that makes the curve's midpoint pass through the pointer, so a dragged line follows the cursor.
export function bendThrough(source: Point, target: Point, pointer: Point): Bend {
  return bendAt(source, target, { x: 2 * pointer.x - (source.x + target.x) / 2, y: 2 * pointer.y - (source.y + target.y) / 2 });
}

function Fields({ title, fields }: { title: string; fields: string[] }) {
  return (
    <div className="mt-3">
      <h4 className={EYEBROW} style={{ color: palette.muted }}>{title}</h4>
      <p className="mt-1 break-words font-mono text-xs">{fields.length ? fields.join(", ") : "none"}</p>
    </div>
  );
}

function NodePanel({ node, onSelectSet, onRunSet, running }: { node: WorkflowNode; onSelectSet: (name: string) => void; onRunSet: (name: string) => void; running: boolean }) {
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: palette.line, background: palette.panel }} aria-live="polite">
      <h3 className="font-mono text-sm font-bold">{node.id}</h3>
      <p className="text-xs" style={{ color: palette.muted }}>{KIND_STYLE[node.kind].label}</p>
      <p className="mt-2 text-sm">{node.description}</p>
      <div className="mt-3">
        <h4 className={EYEBROW} style={{ color: palette.muted }}>{node.models.length > 1 ? "Models, in call order" : "Model"}</h4>
        <p className="mt-1 break-words font-mono text-xs">{node.models.length ? node.models.join(" → ") : "none"}</p>
      </div>
      <Fields title="Reads" fields={node.reads} />
      <Fields title="Writes" fields={node.writes} />
      <div className="mt-3">
        <h4 className={EYEBROW} style={{ color: palette.muted }}>Evals</h4>
        {node.evals.length === 0 ? (
          <p className="mt-1 text-sm">No eval yet.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {node.evals.map((entry) => (
              <li key={entry.set ?? entry.script}>
                {entry.set ? (
                  <span className="flex items-center gap-2">
                    <button type="button" onClick={() => onSelectSet(entry.set!)} className="font-mono font-semibold underline" style={{ color: palette.accent }}>
                      {entry.set}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRunSet(entry.set!)}
                      disabled={running}
                      aria-label={`Run ${entry.set}`}
                      className="rounded-full border px-2.5 py-0.5 text-xs font-semibold disabled:opacity-50"
                      style={{ borderColor: palette.accent, color: palette.accent }}
                    >
                      Run
                    </button>
                  </span>
                ) : (
                  <span>manual, not runnable from the dashboard: <code className="font-mono text-xs">{entry.script}</code></span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function WorkflowMap({ activeSet, onSelectSet, onRunSet, running }: { activeSet: string | null; onSelectSet: (name: string) => void; onRunSet: (name: string) => void; running: boolean }) {
  const [workflow, setWorkflow] = useState<EvalWorkflow | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [lineStyle, setLineStyle] = useState<LineStyle>("curved");
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  // cytoscape loads asynchronously, so the effects that style the canvas re-run once it exists.
  const [cyReady, setCyReady] = useState(false);
  // The canvas tap handler is bound once per workflow, so it reads the latest callback through a ref.
  const pickRef = useRef<(id: string) => void>(() => undefined);

  useEffect(() => {
    pickRef.current = (id: string) => {
      setSelected(id);
      const node = workflow?.nodes.find((entry) => entry.id === id);
      const set = node && runnableSet(node);
      if (set) onSelectSet(set);
    };
  });

  useEffect(() => {
    let alive = true;
    fetchEvalWorkflow()
      .then((next) => alive && setWorkflow(next))
      .catch((cause) => alive && setError(cause instanceof Error ? cause.message : "Unable to load the workflow map"));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!workflow || !containerRef.current) return;
    let cancelled = false;
    const byId = new Map(workflow.nodes.map((node) => [node.id, node]));
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled || !containerRef.current) return;
      const options: CytoscapeOptions = {
        container: containerRef.current,
        elements: [
          ...workflow.nodes.map((node) => ({
            data: { id: node.id, ...nodeLabel(node), kind: node.kind },
            position: positionOf(node),
          })),
          ...workflow.edges.map((edge) => {
            const bend = edgeBend(positionOf(byId.get(edge.source)!), positionOf(byId.get(edge.target)!));
            return {
              data: {
                id: `${edge.source}->${edge.target}`, source: edge.source, target: edge.target, label: edge.label ?? "",
                conditional: edge.conditional ? "yes" : "no", bendDistance: bend.distance, bendWeight: bend.weight,
              },
            };
          }),
        ],
        layout: { name: "preset", fit: true, padding: 16 },
        minZoom: 0.3,
        maxZoom: 2.5,
        style: [
          { selector: "node", style: { shape: "round-rectangle", width: NODE_WIDTH, height: "data(height)", label: "data(label)", "font-size": `${FONT_PX}px`, "line-height": LINE_PX / FONT_PX, "text-max-width": `${NODE_WIDTH - 2 * NODE_PAD}px`, "text-overflow-wrap": "anywhere", "font-family": "ui-monospace, monospace", color: palette.ink, "text-valign": "center", "text-wrap": "wrap", "border-width": 1.5 } },
          ...(Object.keys(KIND_STYLE) as WorkflowNodeKind[]).map((kind) => ({
            selector: `node[kind = '${kind}']`,
            style: { "background-color": KIND_STYLE[kind].fill, "border-color": KIND_STYLE[kind].stroke },
          })),
          { selector: "node.covered", style: { "underlay-color": palette.accent, "underlay-opacity": 0.22, "underlay-padding": 7, "underlay-shape": "round-rectangle" } },
          { selector: "node:selected", style: { "border-width": 3.5, "border-color": palette.failStrong } },
          { selector: "edge", style: { width: 2, "line-color": "#a8a29e", "target-arrow-color": "#a8a29e", "target-arrow-shape": "triangle", "curve-style": "unbundled-bezier", "control-point-distances": "data(bendDistance)", "control-point-weights": "data(bendWeight)", "edge-distances": "node-position", label: "data(label)", "font-size": "9px", color: palette.muted, "text-background-color": palette.page, "text-background-opacity": 1, "text-background-padding": "2px" } },
          { selector: "edge.dragging", style: { "line-color": palette.accent, "target-arrow-color": palette.accent } },
          { selector: "edge.right-angle", style: { "curve-style": "taxi", "taxi-direction": "vertical", "taxi-turn": "50%" } },
          { selector: "edge[conditional = 'yes']", style: { "line-style": "dashed" } },
        ],
      };
      const cy = (cytoscape as unknown as (config: CytoscapeOptions) => Core)(options);
      cy.on("tap", "node", (event: EventObjectNode) => pickRef.current(event.target.id()));
      let dragging: EdgeSingular | null = null;
      cy.on("tapstart", "edge", (event: EventObjectEdge) => {
        dragging = event.target.addClass("dragging");
        cy.userPanningEnabled(false);
      });
      cy.on("tapdrag", (event: EventObject) => {
        if (!dragging) return;
        const bend = bendThrough(dragging.source().position(), dragging.target().position(), event.position);
        dragging.data({ bendDistance: bend.distance, bendWeight: bend.weight });
      });
      cy.on("tapend", () => {
        dragging?.removeClass("dragging");
        dragging = null;
        cy.userPanningEnabled(true);
      });
      cyRef.current = cy;
      setCyReady(true);
    }).catch(() => setError("Workflow map renderer could not be loaded."));
    return () => { cancelled = true; cyRef.current?.destroy(); cyRef.current = null; setCyReady(false); };
  }, [workflow]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selected) return;
    cy.$(":selected").unselect();
    cy.$id(selected).select();
  }, [selected, cyReady]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !workflow) return;
    for (const node of workflow.nodes) cy.$id(node.id).toggleClass("covered", node.evals.some((entry) => entry.set === activeSet));
  }, [activeSet, workflow, cyReady]);

  useEffect(() => {
    cyRef.current?.edges().toggleClass("right-angle", lineStyle === "right-angle");
  }, [lineStyle, cyReady]);

  function zoomBy(factor: number) {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }

  function resetView() {
    const cy = cyRef.current;
    if (!cy || !workflow) return;
    const byId = new Map(workflow.nodes.map((node) => [node.id, node]));
    for (const node of workflow.nodes) cy.$id(node.id).position(positionOf(node));
    for (const edge of workflow.edges) {
      const bend = edgeBend(positionOf(byId.get(edge.source)!), positionOf(byId.get(edge.target)!));
      cy.$id(`${edge.source}->${edge.target}`).data({ bendDistance: bend.distance, bendWeight: bend.weight });
    }
    cy.fit(undefined, 16);
  }

  const node = workflow?.nodes.find((entry) => entry.id === selected);

  return (
    <section aria-labelledby="workflow-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className={EYEBROW} style={{ color: palette.muted }}>Agent graph</p>
          <h2 id="workflow-title" className="text-xl font-bold">Which evals cover which node</h2>
        </div>
        {workflow && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-48">
              <Select
                variant="pill"
                aria-label="Jump to node"
                value={selected ?? ""}
                onChange={(id) => id && pickRef.current(id)}
                options={[{ value: "", label: "Jump to node…" }, ...workflow.nodes.map((entry) => ({ value: entry.id, label: entry.id }))]}
              />
            </div>
            <div className="flex overflow-hidden rounded-lg border" style={{ borderColor: palette.line }} role="group" aria-label="Line style">
              {(["curved", "right-angle"] as const).map((style) => (
                <button
                  key={style}
                  type="button"
                  onClick={() => setLineStyle(style)}
                  aria-pressed={lineStyle === style}
                  className="px-2.5 py-1 font-mono text-xs font-semibold"
                  style={lineStyle === style ? { background: palette.accent, color: palette.onStrong } : { background: palette.panel }}
                >
                  {style}
                </button>
              ))}
            </div>
            <button type="button" onClick={() => zoomBy(1 / ZOOM_STEP)} aria-label="Zoom out" className={TOOL} style={{ borderColor: palette.line, background: palette.panel }}>−</button>
            <button type="button" onClick={() => zoomBy(ZOOM_STEP)} aria-label="Zoom in" className={TOOL} style={{ borderColor: palette.line, background: palette.panel }}>+</button>
            <button type="button" onClick={resetView} className={TOOL} style={{ borderColor: palette.line, background: palette.panel }}>Reset</button>
          </div>
        )}
      </div>
      {error && <p className="mt-2 text-sm" role="alert" style={{ color: palette.warning }}>{error}</p>}
      {!workflow && !error && <p className="mt-2 text-sm" style={{ color: palette.muted }}>Loading the map…</p>}
      {workflow && (
        <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: palette.muted }}>
              {(Object.keys(KIND_STYLE) as WorkflowNodeKind[]).map((kind) => (
                <span key={kind}>
                  <i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border" style={{ background: KIND_STYLE[kind].fill, borderColor: KIND_STYLE[kind].stroke }} />
                  {KIND_STYLE[kind].label}
                </span>
              ))}
              <span>dashed line = conditional edge</span>
              <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: palette.accentSoft }} />covered by the selected set</span>
              <span>scroll or pinch to zoom · drag a node or a line to reshape it · Reset restores the layout</span>
            </div>
            <div ref={containerRef} className="h-[min(680px,75vh)] w-full rounded-xl border" style={{ borderColor: palette.line, background: palette.page }} aria-hidden="true" />
          </div>
          {node ? <NodePanel node={node} onSelectSet={onSelectSet} onRunSet={onRunSet} running={running} /> : (
            <p className="text-sm" style={{ color: palette.muted }}>Click a node to load its eval set below and see what it reads, writes and which model it calls.</p>
          )}
        </div>
      )}
    </section>
  );
}
