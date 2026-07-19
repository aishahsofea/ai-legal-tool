import { PrimaryButton } from "@/components/PrimaryButton";
import { Mono } from "@/components/chamber";
import type { FormEvent } from "react";

export function Composer({
  input,
  onInput,
  onSubmit,
  onStop,
  isLoading,
}: {
  input: string;
  onInput: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onStop: () => void;
  isLoading: boolean;
}) {
  return (
    <div className="border-t border-(--line) bg-(--surface-soft) px-4 pb-3 pt-3 md:px-6 lg:px-8">
      <form onSubmit={onSubmit} className="chamber-full-input chamber-focus-within grid min-h-12 w-full grid-cols-[auto_minmax(0,1fr)_auto_auto] overflow-hidden rounded-xl border border-(--line) bg-(--surface) shadow-[var(--shadow-raised)] max-sm:grid-cols-[minmax(0,1fr)_48px]">
        <span className="flex items-center border-r border-(--line) px-4 text-(--accent) max-sm:hidden">
          <Mono>ASK ›</Mono>
        </span>
        <input
          value={input}
          onChange={(e) => onInput(e.target.value)}
          placeholder="Ask a follow-up, or paste a clause…"
          disabled={isLoading}
          className="min-w-0 bg-transparent px-3 py-2 text-sm text-(--text) outline-none placeholder:text-(--text-subtle) disabled:opacity-50"
        />
        <button type="button" aria-label="Upload" title="Upload document" className="h-full w-10 cursor-pointer border-l border-(--line) text-(--text-subtle) transition-colors duration-200 hover:bg-(--accent-tint) hover:text-(--accent) active:opacity-80 max-sm:hidden">
          ▤
        </button>
        {isLoading ? (
          <PrimaryButton size="compact" type="button" onClick={onStop} aria-label="Stop generating" title="Stop (Esc)" className="h-full rounded-none max-sm:w-12 max-sm:min-w-12 max-sm:px-0">
            <span className="hidden sm:inline">STOP ■</span><span className="sm:hidden">■</span>
          </PrimaryButton>
        ) : (
          <PrimaryButton size="compact" type="submit" aria-label="Send message" disabled={!input.trim()} className="h-full rounded-none disabled:cursor-not-allowed disabled:opacity-40 max-sm:w-12 max-sm:min-w-12 max-sm:px-0">
            <span className="hidden sm:inline">SEND →</span><span className="sm:hidden">↵</span>
          </PrimaryButton>
        )}
      </form>

      <div className="chamber-full-input mt-2 flex w-full justify-between gap-2 px-2 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">
        <span className="max-sm:hidden">DROP A BRIEF OR CONTRACT TO ADD IT TO THE THREAD</span>
        <span className="shrink-0">{isLoading ? "ESC STOP · EDIT" : "⇧⏎ NEWLINE"}</span>
      </div>
    </div>
  );
}
