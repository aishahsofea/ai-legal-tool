import { PillButton } from "@/components/chamber";

const SUGGESTED_QUERIES = [
  "What does section 60A say about overtime pay?",
  "Which Acts govern personal data protection in Malaysia?",
  "What are the penalties under the Penal Code for theft?",
  "How does the Contracts Act treat frustration?",
];

export function EmptyState({ onQuery }: { onQuery: (query: string) => void }) {
  return (
    <div className="space-y-4">
      <div className="border border-(--rule) bg-(--bg-2) p-4">
        <div className="flex items-center gap-2 text-(--ink-3)">
          <span className="font-mono text-[10px] uppercase tracking-widest">LOCUS</span>
          <span className="h-2 w-2 rounded-full bg-(--bronze)" />
          <span className="font-mono text-[10px] uppercase tracking-widest">RESEARCH WORKSPACE</span>
        </div>
        <p className="mt-2 font-serif text-base font-light leading-snug tracking-tight text-(--ink)">
          Ask about statutory text, amendments, and Acts. Locus surfaces governing provisions and keeps the thread anchored to source material.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {SUGGESTED_QUERIES.map((query) => (
          <PillButton key={query} onClick={() => onQuery(query)}>{query}</PillButton>
        ))}
      </div>
    </div>
  );
}
