import { PillButton } from "@/components/chamber";

const SUGGESTED_QUERIES = [
  "What does section 60A say about overtime pay?",
  "Which Acts govern personal data protection in Malaysia?",
  "What are the penalties under the Penal Code for theft?",
  "How does the Contracts Act treat frustration?",
];

function nowLabel(date = new Date()) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function EmptyState({ onQuery }: { onQuery: (query: string) => void }) {
  return (
    <div className="space-y-8">
      <div className="border border-(--rule) bg-(--bg-2) p-6">
        <div className="flex items-center gap-3 text-(--ink-3)">
          <span className="font-mono text-xs uppercase tracking-widest">LOCUS · {nowLabel()}</span>
          <span className="h-1.5 w-1.5 rounded-full bg-(--bronze)" />
          <span className="font-mono text-xs uppercase tracking-widest">RESEARCH WORKSPACE</span>
        </div>
        <p className="mt-4 font-serif text-xl font-light leading-snug tracking-tight text-(--ink)">
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
