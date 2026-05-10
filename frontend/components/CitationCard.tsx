import { Citation } from "@/lib/useQuery";

export function CitationCard({ citation }: { citation: Citation }) {
  return (
    <a
      href={citation.pdf_url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-blue-200 bg-blue-50 text-blue-800 text-sm hover:bg-blue-100 hover:border-blue-300 transition-colors"
    >
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
      <span>
        <span className="font-medium">s.{citation.section_number}</span>
        {" "}
        <span className="text-blue-600">{citation.act_title.replace(/\*/g, "").trim()}</span>
      </span>
      {citation.page_number && (
        <span className="text-blue-400 text-xs">p.{citation.page_number}</span>
      )}
    </a>
  );
}
