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
      <div className="rounded-xl border border-(--line) bg-(--surface) p-4 shadow-[var(--shadow-soft)]">
        <div className="flex items-center gap-2 text-(--text-subtle)">
          <span className="font-mono text-[10px] uppercase tracking-[0.12em]">LOCUS</span>
          <span className="h-2 w-2 rounded-full bg-(--accent)" />
          <span className="font-mono text-[10px] uppercase tracking-[0.12em]">RESEARCH WORKSPACE</span>
        </div>
        <p className="mt-3 max-w-[64ch] font-serif text-lg font-light leading-6 tracking-tight text-(--text)">
          Ask about statutory text, amendments, and Acts. Locus surfaces governing provisions and keeps the thread anchored to source material.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {SUGGESTED_QUERIES.map((query) => (
          <PillButton key={query} onClick={() => onQuery(query)}>{query}</PillButton>
        ))}
      </div>
    </div>
  );
}
