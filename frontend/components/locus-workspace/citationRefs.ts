import type { Citation, CurrencyLabel } from "@/lib/useQuery";

// A schedule citation's section_number is empty (ADR 0018) - path ("sched.2/art.1")
// is its only identifier. Falling back to it keeps the rendered key non-blank.
export function citationMarker(citation: { section_number: string; path?: string }) {
  return citation.section_number || citation.path || "";
}

export function repealWarning(citation: Citation, label: CurrencyLabel) {
  return `Act ${citation.act_number} carries a repeal record dated ${label.as_of_date}. This does not mean Section ${citationMarker(citation)} itself is void — open the repeal record to check.`;
}

export function amendmentNotice(citation: Citation, label: CurrencyLabel) {
  return `Act ${citation.act_number} has been amended since the reprint we indexed (${label.as_of_date}). This does not mean Section ${citationMarker(citation)} itself changed — open the amendment to check.`;
}

export function formatSourceTitle(title: string) {
  return title.replace(/\*/g, "").trim();
}

export function scopedId(...parts: Array<string | number>) {
  return parts.join("-").replace(/[^a-zA-Z0-9_-]/g, "-");
}

export function sourceMapId(messageId: string) {
  return scopedId("source-map", messageId);
}

export function sourceRefId(messageId: string, citation: Citation, index: number) {
  return `source-ref-${scopedId(messageId, citation.act_number, citation.section_number, index)}`;
}
