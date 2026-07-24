export type SerializableGraphState = {
  documentId: string;
  compareDocumentId: string;
  focusProvisionId: string;
  layout: "explore" | "trace";
  view: "base" | "compare" | "overlay";
};

export function serializeReferenceGraphState(state: SerializableGraphState): string {
  const query = new URLSearchParams({
    document_id: state.documentId,
    focus_provision_id: state.focusProvisionId,
    layout: state.layout,
    overlay: state.view,
  });
  if (state.compareDocumentId) query.set("compare_document_id", state.compareDocumentId);
  return `/reference-graph?${query}`;
}
