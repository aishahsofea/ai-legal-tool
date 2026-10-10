"use client";

import type { Core, CytoscapeOptions, EventObjectNode } from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { fetchEvalWorkflow, type EvalWorkflow, type WorkflowNode, type WorkflowNodeKind } from "@/lib/evalsTransport";
import { palette } from "./palette";

const COL = 170;
const ROW = 80;

const KIND_STYLE: Record<WorkflowNodeKind, { label: string; fill: string; stroke: string }> = {
  llm: { label: "LLM call", fill: "#dbeafe", stroke: "#2563eb" },
  deterministic: { label: "deterministic", fill: "#dcfce7", stroke: "#16a34a" },
  control: { label: "control / bookkeeping", fill: "#fef3c7", stroke: "#d97706" },
};

const EYEBROW = "font-mono text-[10px] font-bold uppercase tracking-[0.1em]";

function Fields({ title, fields }: { title: string; fields: string[] }) {
  return (
    <div className="mt-3">
      <h4 className={EYEBROW} style={{ color: palette.muted }}>{title}</h4>
      <p className="mt-1 break-words font-mono text-xs">{fields.length ? fields.join(", ") : "none"}</p>
    </div>
  );
}

function NodePanel({ node, onSelectSet }: { node: WorkflowNode; onSelectSet: (name: string) => void }) {
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: palette.line, background: palette.panel }} aria-live="polite">
      <h3 className="font-mono text-sm font-bold">{node.id}</h3>
      <p className="text-xs" style={{ color: palette.muted }}>{KIND_STYLE[node.kind].label}</p>
      <p className="mt-2 text-sm">{node.description}</p>
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
                  <button type="button" onClick={() => onSelectSet(entry.set!)} className="font-mono font-semibold underline" style={{ color: palette.accent }}>
                    {entry.set}
                  </button>
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

export function WorkflowMap({ onSelectSet }: { onSelectSet: (name: string) => void }) {
  const [workflow, setWorkflow] = useState<EvalWorkflow | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

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
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled || !containerRef.current) return;
      const options: CytoscapeOptions = {
        container: containerRef.current,
        elements: [
          ...workflow.nodes.map((node) => ({
            data: { id: node.id, label: node.id, kind: node.kind },
            position: { x: node.lane * COL, y: node.rank * ROW },
          })),
          ...workflow.edges.map((edge) => ({
            data: { id: `${edge.source}->${edge.target}`, source: edge.source, target: edge.target, label: edge.label ?? "", conditional: edge.conditional ? "yes" : "no" },
          })),
        ],
        layout: { name: "preset", fit: true, padding: 16 },
        userZoomingEnabled: false,
        style: [
          { selector: "node", style: { shape: "round-rectangle", width: 132, height: 30, label: "data(label)", "font-size": "10px", "font-family": "ui-monospace, monospace", color: palette.ink, "text-valign": "center", "border-width": 1.5 } },
          ...(Object.keys(KIND_STYLE) as WorkflowNodeKind[]).map((kind) => ({
            selector: `node[kind = '${kind}']`,
            style: { "background-color": KIND_STYLE[kind].fill, "border-color": KIND_STYLE[kind].stroke },
          })),
          { selector: "node:selected", style: { "border-width": 3.5, "border-color": palette.failStrong } },
          { selector: "edge", style: { width: 1.5, "line-color": "#a8a29e", "target-arrow-color": "#a8a29e", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": "9px", color: palette.muted, "text-background-color": palette.page, "text-background-opacity": 1, "text-background-padding": "2px" } },
          { selector: "edge[conditional = 'yes']", style: { "line-style": "dashed" } },
        ],
      };
      const cy = (cytoscape as unknown as (config: CytoscapeOptions) => Core)(options);
      cy.on("tap", "node", (event: EventObjectNode) => setSelected(event.target.id()));
      cyRef.current = cy;
    }).catch(() => setError("Workflow map renderer could not be loaded."));
    return () => { cancelled = true; cyRef.current?.destroy(); cyRef.current = null; };
  }, [workflow]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selected) return;
    cy.$(":selected").unselect();
    cy.$id(selected).select();
  }, [selected, workflow]);

  const node = workflow?.nodes.find((entry) => entry.id === selected);

  return (
    <section className="px-4 sm:px-0" aria-labelledby="workflow-title">
      <p className={EYEBROW} style={{ color: palette.muted }}>Agent graph</p>
      <h2 id="workflow-title" className="text-xl font-bold">Which evals cover which node</h2>
      {error && <p className="mt-2 text-sm" role="alert" style={{ color: palette.warning }}>{error}</p>}
      {!workflow && !error && <p className="mt-2 text-sm" style={{ color: palette.muted }}>Loading the map…</p>}
      {workflow && (
        <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: palette.muted }}>
              {(Object.keys(KIND_STYLE) as WorkflowNodeKind[]).map((kind) => (
                <span key={kind}>
                  <i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border" style={{ background: KIND_STYLE[kind].fill, borderColor: KIND_STYLE[kind].stroke }} />
                  {KIND_STYLE[kind].label}
                </span>
              ))}
              <span>dashed line = conditional edge</span>
            </div>
            <div ref={containerRef} className="h-[520px] w-full rounded-xl border" style={{ borderColor: palette.line, background: palette.page }} aria-hidden="true" />
            <ul className="flex flex-wrap gap-1.5" aria-label="Graph nodes">
              {workflow.nodes.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(entry.id)}
                    aria-pressed={entry.id === selected}
                    className="rounded-full border px-2.5 py-1 font-mono text-xs"
                    style={{ borderColor: entry.id === selected ? palette.failStrong : KIND_STYLE[entry.kind].stroke, background: KIND_STYLE[entry.kind].fill, color: palette.ink }}
                  >
                    {entry.id}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {node ? <NodePanel node={node} onSelectSet={onSelectSet} /> : (
            <p className="text-sm" style={{ color: palette.muted }}>Pick a node to see what it reads, writes and which evals cover it.</p>
          )}
        </div>
      )}
    </section>
  );
}
