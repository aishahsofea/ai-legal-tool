import { Citation } from "@/lib/useQuery";

export function CitationCard({ citation }: { citation: Citation }) {
  return (
    <a
      href={citation.pdf_url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-2 rounded-xl border border-(--accent-line) bg-(--accent-tint) px-3 py-2 transition-colors duration-200 hover:bg-(--accent-soft)"
    >
      <span className="font-mono text-xs uppercase tracking-[0.12em] text-(--accent)">§ {citation.section_number}</span>
      <span className="font-serif text-sm font-light text-(--text)">{citation.act_title.replace(/\*/g, "").trim()}</span>
      {citation.page_number && <span className="font-mono text-xs uppercase tracking-[0.12em] text-(--text-subtle)">p. {citation.page_number}</span>}
    </a>
  );
}
