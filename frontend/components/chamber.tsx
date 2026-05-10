import { Citation } from "@/lib/useQuery";
import { type ButtonHTMLAttributes, type ReactNode } from "react";

export function Mono({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`font-mono text-[10px] uppercase tracking-widest ${className}`}
    >
      {children}
    </span>
  );
}

export function Mark() {
  return (
    <div className="flex items-center gap-2 text-(--bronze)">
      <svg viewBox="0 0 28 28" fill="none" className="h-4 w-4">
        <circle cx="14" cy="14" r="13" stroke="currentColor" strokeWidth="1" />
        <circle cx="14" cy="14" r="3" fill="currentColor" />
        <line
          x1="14"
          y1="1"
          x2="14"
          y2="6"
          stroke="currentColor"
          strokeWidth="1"
        />
        <line
          x1="14"
          y1="22"
          x2="14"
          y2="27"
          stroke="currentColor"
          strokeWidth="1"
        />
      </svg>
      <span className="text-xs font-semibold tracking-widest text-(--ink)">
        LOCUS
      </span>
    </div>
  );
}

export function OutlineButton({
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`inline-flex cursor-pointer items-center justify-center rounded-sm border border-(--rule) px-2 py-2 text-xs text-(--ink-2) transition-colors duration-150 hover:border-(--bronze) hover:text-(--bronze) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-(--rule) disabled:hover:text-(--ink-2) ${className}`}
    >
      {children}
    </button>
  );
}

export function PillButton({
  className = "",
  children,
  style,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{ fontSize: 12, ...style }}
      className={`cursor-pointer rounded-full border border-(--rule) px-4 py-2 text-xs text-left text-(--ink-2) transition-colors duration-150 hover:border-(--bronze) hover:bg-(--bg-2) hover:text-(--bronze) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-(--rule) disabled:hover:bg-transparent disabled:hover:text-(--ink-2) ${className}`}
    >
      {children}
    </button>
  );
}

export function ThreadRow({
  title,
  meta,
  active = false,
}: {
  title: string;
  meta: string;
  active?: boolean;
}) {
  return (
    <button
      type="button"
      className={`flex w-full cursor-pointer items-stretch gap-2 rounded-sm px-2 py-2 text-left transition-colors duration-150 hover:bg-(--bg-2) active:opacity-80 ${
        active ? "bg-(--bg-2)" : "bg-transparent"
      }`}
    >
      <span
        className={`w-[2px] shrink-0 rounded-full ${active ? "bg-(--bronze)" : "bg-transparent"}`}
      />
      <div>
        <div className="text-xs leading-snug text-(--ink)">{title}</div>
        <div className="mt-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
          {meta}
        </div>
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
      className={`w-full cursor-pointer border-b border-(--rule-soft) px-2 py-2 text-left transition-colors duration-150 hover:bg-(--bg-2) active:opacity-80 ${
        active ? "bg-(--bronze-tint)" : "bg-transparent"
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <Mono className="text-(--bronze)">§ {citation.section_number}</Mono>
        <span className="rounded-sm bg-(--rule-soft) px-2 py-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
          ×2
        </span>
      </div>
      <div className="font-serif text-xs font-light leading-snug text-(--ink)">
        {citation.act_title.replace(/\*/g, "").trim()}
      </div>
      <div className="mt-2 font-serif text-xs italic text-(--ink-3)">
        {citation.page_number
          ? `p. ${citation.page_number}`
          : "Selected source"}
      </div>
    </button>
  );
}
