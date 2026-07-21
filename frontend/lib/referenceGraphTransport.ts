import { API_URL } from "@/lib/queryTransport";

export type ReferenceGraphStatus = "available" | "not_indexed" | "provision_not_found" | "graph_unavailable" | "flag-off";

export type GraphEvidence = {
  text: string;
  start_offset: number;
  end_offset: number;
  pages: Array<{ page_number: number; rectangles: Array<{ x: number; y: number; width: number; height: number }> }>;
};

export type GraphNode = {
  provision_id: string;
  version_id: string;
  label: string;
  kind: string;
  page_start: number;
  page_end: number;
};

export type GraphEdge = {
  edge_id: string;
  source_provision_id: string;
  target_provision_id: string;
  relationship: string;
  reference_kind: string;
  evidence: GraphEvidence;
};

export type Neighborhood = {
  status: ReferenceGraphStatus;
  document_id: string;
  focus_provision_id?: string;
  nodes?: GraphNode[];
  edges?: GraphEdge[];
};

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function status(value: unknown): value is ReferenceGraphStatus {
  return value === "available" || value === "not_indexed" || value === "provision_not_found" || value === "graph_unavailable" || value === "flag-off";
}

export function decodeNeighborhood(value: unknown, expectedDocumentId: string): Neighborhood {
  if (!record(value) || !status(value.status) || value.document_id !== expectedDocumentId) {
    throw new Error("Reference graph API returned malformed data.");
  }
  if (value.status !== "available") return { status: value.status, document_id: expectedDocumentId };
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges) || typeof value.focus_provision_id !== "string") {
    throw new Error("Reference graph API returned incomplete neighborhood data.");
  }
  const nodes = value.nodes.map((node) => {
    if (!record(node) || typeof node.provision_id !== "string" || typeof node.version_id !== "string" || typeof node.label !== "string"
      || typeof node.kind !== "string" || !Number.isInteger(node.page_start) || !Number.isInteger(node.page_end)) {
      throw new Error("Reference graph API returned malformed nodes.");
    }
    return node as unknown as GraphNode;
  });
  const edges = value.edges.map((edge) => {
    if (!record(edge) || typeof edge.edge_id !== "string" || typeof edge.source_provision_id !== "string"
      || typeof edge.target_provision_id !== "string" || !record(edge.evidence) || typeof edge.evidence.text !== "string") {
      throw new Error("Reference graph API returned malformed edges.");
    }
    return edge as unknown as GraphEdge;
  });
  return { status: "available", document_id: expectedDocumentId, focus_provision_id: value.focus_provision_id, nodes, edges };
}

export async function fetchNeighborhood(documentId: string, focusProvisionId: string, signal?: AbortSignal): Promise<Neighborhood> {
  const query = new URLSearchParams({ document_id: documentId, focus_provision_id: focusProvisionId });
  const response = await fetch(`${API_URL}/reference-graph/neighborhood?${query}`, { signal });
  if (!response.ok) throw new Error(`Reference graph API returned HTTP ${response.status}.`);
  return decodeNeighborhood(await response.json(), documentId);
}
