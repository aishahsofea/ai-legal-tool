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
    <div className="border-t border-(--rule) px-4 pb-6 pt-3 lg:px-16">
      <form onSubmit={onSubmit} className="mx-auto grid chamber-max-input chamber-grid-composer overflow-hidden rounded-sm border border-(--rule) bg-(--bg-2) chamber-focus-within">
        <span className="flex items-center border-r border-(--rule) px-4 text-(--bronze)">
          <Mono>ASK ›</Mono>
        </span>
        <input
          value={input}
          onChange={(e) => onInput(e.target.value)}
          placeholder="Ask a follow-up, or paste a clause…"
          disabled={isLoading}
          className="min-w-0 bg-transparent px-4 py-3 text-sm text-(--ink) outline-none placeholder:text-(--ink-3) disabled:opacity-50"
        />
        <button type="button" aria-label="Upload" className="h-full w-10 border-l border-(--rule) text-(--ink-3) transition-colors duration-150 hover:text-(--bronze)">
          ▤
        </button>
        <PrimaryButton type="submit" disabled={isLoading || !input.trim()} className="h-full px-5 disabled:cursor-not-allowed disabled:opacity-40">
          SEND →
        </PrimaryButton>
      </form>

      <div className="mx-auto mt-2 flex chamber-max-input justify-between gap-4 px-1 font-mono text-xs uppercase tracking-widest text-(--ink-3)">
        <span>DROP A BRIEF OR CONTRACT TO ADD IT TO THE THREAD</span>
        <span>⇧⏎ NEWLINE</span>
      </div>
    </div>
  );
}
