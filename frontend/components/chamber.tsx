import { Citation } from "@/lib/useQuery";
import { type ButtonHTMLAttributes, type ReactNode } from "react";

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-xs uppercase tracking-widest ${className}`}>{children}</span>;
}

export function Mark() {
  return (
    <div className="flex items-center gap-2 text-(--bronze)">
      <svg viewBox="0 0 28 28" fill="none" className="h-5 w-5">
        <circle cx="14" cy="14" r="13" stroke="currentColor" strokeWidth="1" />
        <circle cx="14" cy="14" r="3" fill="currentColor" />
        <line x1="14" y1="1" x2="14" y2="6" stroke="currentColor" strokeWidth="1" />
        <line x1="14" y1="22" x2="14" y2="27" stroke="currentColor" strokeWidth="1" />
      </svg>
      <span className="text-sm font-semibold tracking-widest text-(--ink)">LOCUS</span>
    </div>
  );
}

export function OutlineButton({ className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-sm border border-(--rule) px-3 py-1.5 text-sm text-(--ink-2) transition-colors duration-150 hover:border-(--bronze) hover:text-(--bronze) ${className}`}
    >
      {children}
    </button>
  );
}

export function PillButton({ className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`rounded-full border border-(--rule) px-4 py-2 text-left text-sm text-(--ink-2) transition-colors duration-150 hover:border-(--bronze) hover:bg-(--bg-2) hover:text-(--bronze) ${className}`}
    >
      {children}
    </button>
  );
}

export function ThreadRow({ title, meta, active = false }: { title: string; meta: string; active?: boolean }) {
  return (
    <button
      type="button"
      className={`flex w-full items-stretch gap-2 rounded-sm px-2 py-2 text-left transition-colors duration-150 hover:bg-(--bg-2) ${
        active ? "bg-(--bg-2)" : "bg-transparent"
      }`}
    >
      <span className={`w-0.5 shrink-0 rounded-full ${active ? "bg-(--bronze)" : "bg-transparent"}`} />
      <div>
        <div className="text-sm leading-snug text-(--ink)">{title}</div>
        <div className="mt-1 font-mono text-xs uppercase tracking-widest text-(--ink-3)">{meta}</div>
      </div>
    </button>
  );
}

export function SourceChip({
  citation,
  active,
  onClick,
}: {
  citation: Citation;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full border-b border-(--rule-soft) px-4 py-3 text-left transition-colors duration-150 hover:bg-(--bg-2) ${
        active ? "bg-(--bronze-tint)" : "bg-transparent"
      }`}
    >
      <div className="mb-1 flex items-center justify-between gap-3">
        <Mono className="text-(--bronze)">§ {citation.section_number}</Mono>
        <span className="rounded-sm bg-(--rule-soft) px-1.5 py-0.5 font-mono text-xs uppercase tracking-widest text-(--ink-3)">
          ×2
        </span>
      </div>
      <div className="font-serif text-sm font-light leading-snug text-(--ink)">{citation.act_title.replace(/\*/g, "").trim()}</div>
      <div className="mt-1 font-serif text-sm italic text-(--ink-3)">
        {citation.page_number ? `p. ${citation.page_number}` : "Selected source"}
      </div>
    </button>
  );
}
