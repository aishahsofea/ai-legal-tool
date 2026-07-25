import { API_URL } from "@/lib/queryTransport";

export type ReferenceGraphStatus = "available" | "not_indexed" | "provision_not_found" | "graph_unavailable" | "flag-off";
export type ComparisonStatus = "available" | "not_indexed_base" | "not_indexed_compare" | "focus_missing_base"
  | "focus_missing_compare" | "comparison_disabled" | "graph_unavailable";
export type ComparisonEdgeStatus = "added" | "removed" | "unchanged";

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

export type GraphSnapshot = {
  document_id: string;
  corpus_document_id: string;
  act_number: string;
  act_title: string;
  language: string;
  snapshot_date: string;
  snapshot_type: string;
  source_url: string;
  sha256: string;
  byte_size: number;
  page_count: number;
  receipt_path: string;
};

export type SnapshotCatalog = {
  status: "available" | "comparison_disabled" | "flag-off" | "graph_unavailable";
  comparison_enabled: boolean;
  snapshots: GraphSnapshot[];
};

export type ComparisonNode = {
  provision_id: string;
  presence: "base" | "compare" | "both";
  base_node: GraphNode | null;
  compare_node: GraphNode | null;
};

export type LogicalReference = {
  logical_reference_id: string;
  logical_key: {
    source_provision_id: string;
    target_provision_id: string;
    reference_kind: string;
    relationship: string;
    literal_wording: string;
  };
  occurrence_ordinal: number;
  status: ComparisonEdgeStatus;
  base_edge: GraphEdge | null;
  compare_edge: GraphEdge | null;
};

export type GraphComparison = {
  status: ComparisonStatus;
  base_document_id: string;
  compare_document_id: string;
  focus_provision_id?: string;
  focus_presence?: { base: boolean; compare: boolean };
  counts?: Record<ComparisonEdgeStatus, number>;
  nodes?: ComparisonNode[];
  references?: LogicalReference[];
};

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function status(value: unknown): value is ReferenceGraphStatus {
  return value === "available" || value === "not_indexed" || value === "provision_not_found" || value === "graph_unavailable" || value === "flag-off";
}

function comparisonStatus(value: unknown): value is ComparisonStatus {
  return value === "available" || value === "not_indexed_base" || value === "not_indexed_compare"
    || value === "focus_missing_base" || value === "focus_missing_compare"
    || value === "comparison_disabled" || value === "graph_unavailable";
}

function decodeNode(value: unknown): GraphNode {
  if (!record(value) || typeof value.provision_id !== "string" || typeof value.version_id !== "string"
    || typeof value.label !== "string" || typeof value.kind !== "string"
    || !Number.isInteger(value.page_start) || !Number.isInteger(value.page_end)) {
    throw new Error("Reference graph API returned malformed nodes.");
  }
  return value as unknown as GraphNode;
}

function decodeEdge(value: unknown): GraphEdge {
  if (!record(value) || typeof value.edge_id !== "string" || typeof value.source_provision_id !== "string"
    || typeof value.target_provision_id !== "string" || typeof value.relationship !== "string"
    || typeof value.reference_kind !== "string" || !record(value.evidence)
    || typeof value.evidence.text !== "string" || !Number.isInteger(value.evidence.start_offset)
    || !Number.isInteger(value.evidence.end_offset) || !Array.isArray(value.evidence.pages)) {
    throw new Error("Reference graph API returned malformed edges.");
  }
  return value as unknown as GraphEdge;
}

export function decodeNeighborhood(value: unknown, expectedDocumentId: string): Neighborhood {
  if (!record(value) || !status(value.status) || value.document_id !== expectedDocumentId) {
    throw new Error("Reference graph API returned malformed data.");
  }
  if (value.status !== "available") return { status: value.status, document_id: expectedDocumentId };
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges) || typeof value.focus_provision_id !== "string") {
    throw new Error("Reference graph API returned incomplete neighborhood data.");
  }
  return {
    status: "available",
    document_id: expectedDocumentId,
    focus_provision_id: value.focus_provision_id,
    nodes: value.nodes.map(decodeNode),
    edges: value.edges.map(decodeEdge),
  };
}

export function decodeSnapshotCatalog(value: unknown): SnapshotCatalog {
  if (!record(value) || (value.status !== "available" && value.status !== "comparison_disabled"
    && value.status !== "flag-off" && value.status !== "graph_unavailable")
    || !Array.isArray(value.snapshots)) {
    throw new Error("Reference graph snapshot catalog returned malformed data.");
  }
  if (value.status !== "available") {
    return { status: value.status, comparison_enabled: false, snapshots: [] };
  }
  const snapshots = value.snapshots.map((item) => {
    if (!record(item) || typeof item.document_id !== "string" || typeof item.corpus_document_id !== "string"
      || typeof item.act_number !== "string" || typeof item.act_title !== "string" || typeof item.language !== "string"
      || typeof item.snapshot_date !== "string" || typeof item.snapshot_type !== "string" || typeof item.source_url !== "string"
      || typeof item.sha256 !== "string" || !Number.isInteger(item.byte_size) || !Number.isInteger(item.page_count)
      || typeof item.receipt_path !== "string") {
      throw new Error("Reference graph snapshot catalog returned malformed snapshots.");
    }
    return item as unknown as GraphSnapshot;
  });
  return { status: "available", comparison_enabled: value.comparison_enabled === true, snapshots };
}

export function decodeComparison(value: unknown, baseDocumentId: string, compareDocumentId: string): GraphComparison {
  if (!record(value) || !comparisonStatus(value.status) || value.base_document_id !== baseDocumentId
    || value.compare_document_id !== compareDocumentId) {
    throw new Error("Reference graph comparison API returned malformed data.");
  }
  if (value.status !== "available") {
    return {
      status: value.status,
      base_document_id: baseDocumentId,
      compare_document_id: compareDocumentId,
      focus_provision_id: typeof value.focus_provision_id === "string" ? value.focus_provision_id : undefined,
      focus_presence: record(value.focus_presence)
        ? { base: value.focus_presence.base === true, compare: value.focus_presence.compare === true }
        : undefined,
    };
  }
  if (typeof value.focus_provision_id !== "string" || !record(value.counts)
    || !Array.isArray(value.nodes) || !Array.isArray(value.references)) {
    throw new Error("Reference graph comparison API returned incomplete data.");
  }
  const counts = {
    added: Number(value.counts.added),
    removed: Number(value.counts.removed),
    unchanged: Number(value.counts.unchanged),
  };
  if (Object.values(counts).some((count) => !Number.isInteger(count) || count < 0)) {
    throw new Error("Reference graph comparison API returned malformed counts.");
  }
  const nodes = value.nodes.map((item) => {
    if (!record(item) || typeof item.provision_id !== "string"
      || (item.presence !== "base" && item.presence !== "compare" && item.presence !== "both")) {
      throw new Error("Reference graph comparison API returned malformed nodes.");
    }
    return {
      provision_id: item.provision_id,
      presence: item.presence,
      base_node: item.base_node === null ? null : decodeNode(item.base_node),
      compare_node: item.compare_node === null ? null : decodeNode(item.compare_node),
    } as ComparisonNode;
  });
  const references = value.references.map((item) => {
    if (!record(item) || typeof item.logical_reference_id !== "string" || !record(item.logical_key)
      || !Number.isInteger(item.occurrence_ordinal)
      || (item.status !== "added" && item.status !== "removed" && item.status !== "unchanged")) {
      throw new Error("Reference graph comparison API returned malformed references.");
    }
    const key = item.logical_key;
    if (typeof key.source_provision_id !== "string" || typeof key.target_provision_id !== "string"
      || typeof key.reference_kind !== "string" || typeof key.relationship !== "string"
      || typeof key.literal_wording !== "string") {
      throw new Error("Reference graph comparison API returned malformed logical keys.");
    }
    return {
      logical_reference_id: item.logical_reference_id,
      logical_key: key,
      occurrence_ordinal: item.occurrence_ordinal,
      status: item.status,
      base_edge: item.base_edge === null ? null : decodeEdge(item.base_edge),
      compare_edge: item.compare_edge === null ? null : decodeEdge(item.compare_edge),
    } as LogicalReference;
  });
  return {
    status: "available",
    base_document_id: baseDocumentId,
    compare_document_id: compareDocumentId,
    focus_provision_id: value.focus_provision_id,
    focus_presence: { base: true, compare: true },
    counts,
    nodes,
    references,
  };
}

export async function fetchNeighborhood(documentId: string, focusProvisionId: string, signal?: AbortSignal): Promise<Neighborhood> {
  const query = new URLSearchParams({ document_id: documentId, focus_provision_id: focusProvisionId });
  const response = await fetch(`${API_URL}/reference-graph/neighborhood?${query}`, { signal });
  if (!response.ok) throw new Error(`Reference graph API returned HTTP ${response.status}.`);
  return decodeNeighborhood(await response.json(), documentId);
}

export async function fetchSnapshots(signal?: AbortSignal): Promise<SnapshotCatalog> {
  const response = await fetch(`${API_URL}/reference-graph/snapshots?act_number=265&language=en`, { signal });
  if (!response.ok) throw new Error(`Reference graph snapshot catalog returned HTTP ${response.status}.`);
  return decodeSnapshotCatalog(await response.json());
}

export async function fetchComparison(
  baseDocumentId: string,
  compareDocumentId: string,
  focusProvisionId: string,
  signal?: AbortSignal,
): Promise<GraphComparison> {
  const query = new URLSearchParams({
    base_document_id: baseDocumentId,
    compare_document_id: compareDocumentId,
    focus_provision_id: focusProvisionId,
  });
  const response = await fetch(`${API_URL}/reference-graph/compare?${query}`, { signal });
  if (!response.ok) throw new Error(`Reference graph comparison API returned HTTP ${response.status}.`);
  return decodeComparison(await response.json(), baseDocumentId, compareDocumentId);
}
