import { PrimaryButton } from "@/components/PrimaryButton";
import { Mono } from "@/components/chamber";
import type { FormEvent } from "react";

export function Composer({
  input,
  onInput,
  onSubmit,
  isLoading,
}: {
  input: string;
  onInput: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  isLoading: boolean;
}) {
  return (
    <div className="border-t border-(--rule) px-4 pb-4 pt-2 lg:px-20">
      <form onSubmit={onSubmit} className="mx-auto grid chamber-max-input chamber-grid-composer overflow-hidden rounded-sm border border-(--rule) bg-(--bg-2) chamber-focus-within">
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
        <button type="button" aria-label="Upload" title="Upload document" className="h-full w-8 cursor-pointer border-l border-(--rule) text-(--ink-3) transition-colors duration-150 hover:text-(--bronze) active:opacity-80">
          ▤
        </button>
        <PrimaryButton type="submit" disabled={isLoading || !input.trim()} className="h-full px-4 disabled:cursor-not-allowed disabled:opacity-40">
          SEND →
        </PrimaryButton>
      </form>

      <div className="mx-auto mt-2 flex chamber-max-input justify-between gap-2 px-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
        <span>DROP A BRIEF OR CONTRACT TO ADD IT TO THE THREAD</span>
        <span>⇧⏎ NEWLINE</span>
      </div>
    </div>
  );
}
