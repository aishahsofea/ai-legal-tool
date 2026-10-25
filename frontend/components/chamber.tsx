import { Citation } from "@/lib/useQuery";
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Trash } from "@/components/icons";

export function Mono({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`font-mono text-[10px] font-medium uppercase tracking-[0.12em] ${className}`}
    >
      {children}
    </span>
  );
}

export function Mark() {
  return (
    <div className="flex items-center gap-2 text-(--accent)">
      <svg viewBox="0 0 28 28" fill="none" className="h-5 w-5">
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
      <span className="text-xs font-semibold tracking-[0.2em] text-(--text)">
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
      className={`inline-flex min-h-8 cursor-pointer items-center justify-center rounded-lg border border-(--line) bg-(--surface) px-3 py-1 text-xs leading-4 text-(--text-muted) transition-colors duration-200 hover:border-(--accent-line) hover:bg-(--accent-tint) hover:text-(--accent) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-(--line) disabled:hover:bg-(--surface) disabled:hover:text-(--text-muted) ${className}`}
    >
      {children}
    </button>
  );
}

export function IconButton({
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-(--text-subtle) transition-colors duration-150 hover:bg-(--line-soft) hover:text-(--text) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-(--text-subtle) ${className}`}
    >
      {children}
    </button>
  );
}

export function PillButton({
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`min-h-10 cursor-pointer rounded-lg border border-(--line) bg-(--surface) px-3 py-2 text-left text-sm leading-5 text-(--text-muted) shadow-[var(--shadow-soft)] transition-colors duration-200 hover:border-(--accent-line) hover:bg-(--accent-tint) hover:text-(--accent) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-(--line) disabled:hover:bg-(--surface) disabled:hover:text-(--text-muted) ${className}`}
    >
      {children}
    </button>
  );
}

export function ThreadRow({
  title,
  meta,
  active = false,
  disabled = false,
  onClick,
  onDelete,
  deleteDisabled = false,
}: {
  title: string;
  meta: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  onDelete?: () => void;
  deleteDisabled?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="group relative max-md:min-w-[224px]">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={`flex w-full cursor-pointer items-stretch gap-2 rounded-lg px-3 py-2 text-left transition-colors duration-200 hover:bg-(--surface) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 ${
          onDelete ? "pr-10" : ""
        } ${active ? "bg-(--surface) shadow-[var(--shadow-soft)]" : "bg-transparent"}`}
      >
        <span
          className={`w-[2px] shrink-0 rounded-full ${active ? "bg-(--accent)" : "bg-transparent"}`}
        />
        <div className="min-w-0">
          <div className="truncate text-sm leading-5 text-(--text)">{title}</div>
          <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">
            {meta}
          </div>
        </div>
      </button>
      {onDelete && (
        <IconButton
          type="button"
          aria-label={`Delete thread ${title}`}
          disabled={deleteDisabled}
          onClick={() => setConfirming(true)}
          className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 max-md:opacity-100"
        >
          <Trash />
        </IconButton>
      )}
      {onDelete && confirming && (
        <DeleteThreadDialog
          title={title}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            onDelete();
          }}
        />
      )}
    </div>
  );
}

function DeleteThreadDialog({
  title,
  onCancel,
  onConfirm,
}: {
  title: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => dialogRef.current?.querySelector("button")?.focus(), []);
  // Portaled to body so the sidebar's overflow and stacking can't clip or cover it.
  return createPortal(
    <div
      data-testid="delete-dialog-backdrop"
      onClick={onCancel}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-thread-title"
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.key === "Escape" && onCancel()}
        className="w-full max-w-sm rounded-xl border border-(--line) bg-(--surface) p-5 shadow-[var(--shadow-raised)]"
      >
        <h2 id="delete-thread-title" className="text-base font-medium text-(--text)">
          Delete thread?
        </h2>
        <p className="mt-2 text-sm leading-5 text-(--text-muted)">
          “{title}” and its messages will be permanently deleted. This can’t be undone.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <OutlineButton type="button" onClick={onCancel} className="min-h-9 px-4 text-sm">
            Cancel
          </OutlineButton>
          <button
            type="button"
            onClick={onConfirm}
            className="min-h-9 cursor-pointer rounded-lg bg-(--danger) px-4 text-sm text-white transition-opacity duration-200 hover:opacity-90 active:opacity-80"
          >
            Delete
          </button>
        </div>
      </div>
    </div>,
    document.body,
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
      className={`w-full cursor-pointer border-b border-(--line-soft) px-3 py-3 text-left transition-colors duration-200 hover:bg-(--surface) active:opacity-80 ${
        active ? "bg-(--accent-tint)" : "bg-transparent"
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <Mono className="text-(--accent)">§ {citation.section_number}</Mono>
        <span className="rounded-md bg-(--surface-strong) px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">
          ×2
        </span>
      </div>
      <div className="font-serif text-sm font-light leading-5 text-(--text)">
        {citation.act_title.replace(/\*/g, "").trim()}
      </div>
      <div className="mt-2 font-serif text-xs italic text-(--text-subtle)">
        {citation.page_number
          ? `p. ${citation.page_number}`
          : "Selected source"}
      </div>
    </button>
  );
}
