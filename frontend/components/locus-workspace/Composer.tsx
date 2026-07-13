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
    <div className="border-t border-(--rule) px-4 pb-4 pt-2 md:px-8 xl:px-12">
      <form onSubmit={onSubmit} className="grid w-full chamber-full-input chamber-grid-composer max-sm:grid-cols-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-sm border border-(--rule) bg-(--bg-2) chamber-focus-within">
        <span className="flex items-center border-r border-(--rule) px-4 text-(--bronze)">
          <Mono>ASK ›</Mono>
        </span>
        <input
          value={input}
          onChange={(e) => onInput(e.target.value)}
          placeholder="Ask a follow-up, or paste a clause…"
          disabled={isLoading}
          className="min-w-0 bg-transparent px-2 py-2 text-sm text-(--ink) outline-none placeholder:text-(--ink-3) disabled:opacity-50"
        />
        <button type="button" aria-label="Upload" title="Upload document" className="h-full w-8 cursor-pointer border-l border-(--rule) text-(--ink-3) transition-colors duration-150 hover:text-(--bronze) active:opacity-80 max-sm:hidden">
          ▤
        </button>
        {isLoading ? (
          <PrimaryButton type="button" onClick={onStop} aria-label="Stop generating" title="Stop (Esc)" className="h-full px-3 sm:px-4">
            <span className="hidden sm:inline">STOP ■</span><span className="sm:hidden">■</span>
          </PrimaryButton>
        ) : (
          <PrimaryButton type="submit" disabled={!input.trim()} className="h-full px-3 sm:px-4 disabled:cursor-not-allowed disabled:opacity-40">
            <span className="hidden sm:inline">SEND →</span><span className="sm:hidden">↵</span>
          </PrimaryButton>
        )}
      </form>

      <div className="mt-2 flex w-full chamber-full-input justify-between gap-2 px-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
        <span>DROP A BRIEF OR CONTRACT TO ADD IT TO THE THREAD</span>
        <span>{isLoading ? "ESC STOP · EDIT" : "⇧⏎ NEWLINE"}</span>
      </div>
    </div>
  );
}
