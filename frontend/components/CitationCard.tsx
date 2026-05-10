import { Citation } from "@/lib/useQuery";

export function CitationCard({ citation }: { citation: Citation }) {
  return (
    <a
      href={citation.pdf_url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-2 rounded-sm border border-(--bronze) bg-(--bronze-tint) px-2 py-2 transition-colors duration-150 hover:bg-(--bronze-soft)"
    >
      <span className="font-mono text-xs uppercase tracking-widest text-(--bronze)">§ {citation.section_number}</span>
      <span className="font-serif text-sm font-light text-(--ink)">{citation.act_title.replace(/\*/g, "").trim()}</span>
      {citation.page_number && <span className="font-mono text-xs uppercase tracking-widest text-(--ink-3)">p. {citation.page_number}</span>}
    </a>
  );
}
