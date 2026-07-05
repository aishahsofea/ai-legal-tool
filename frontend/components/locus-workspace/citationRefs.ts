import type { Citation } from "@/lib/useQuery";

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
