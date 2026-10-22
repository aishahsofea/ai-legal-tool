import { PrimaryButton } from "@/components/PrimaryButton";
import { Mono } from "@/components/chamber";
import { type FormEvent, useLayoutEffect, useRef } from "react";

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  return (
    <div className="border-t border-(--line) bg-(--surface-soft) px-4 pb-3 pt-3 md:px-6 lg:px-8">
      <form onSubmit={onSubmit} className="chamber-full-input chamber-focus-within grid min-h-12 w-full items-center grid-cols-[auto_minmax(0,1fr)_auto_auto] overflow-hidden rounded-xl border border-(--line) bg-(--surface) shadow-[var(--shadow-raised)] max-sm:grid-cols-[minmax(0,1fr)_48px]">
        <span className="flex items-center self-stretch border-r border-(--line) px-4 text-(--accent) max-sm:hidden">
          <Mono>ASK ›</Mono>
        </span>
        <textarea
          ref={textareaRef}
          rows={1}
          aria-label="Message"
          value={input}
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" || e.shiftKey) return;
            // keyCode 229 covers IME engines that omit isComposing on the confirming Enter
            if (e.nativeEvent.isComposing || e.keyCode === 229) return;
            e.preventDefault();
            if (input.trim()) e.currentTarget.form?.requestSubmit();
          }}
          placeholder="Ask a follow-up, or paste a clause…"
          disabled={isLoading}
          className="max-h-[min(136px,20dvh)] min-w-0 resize-none overflow-y-auto bg-transparent px-3 py-2 text-sm leading-5 text-(--text) outline-none placeholder:text-(--text-subtle) disabled:opacity-50"
        />
        <button type="button" aria-label="Upload" title="Upload document" className="h-full w-10 cursor-pointer self-stretch border-l border-(--line) text-(--text-subtle) transition-colors duration-200 hover:bg-(--accent-tint) hover:text-(--accent) active:opacity-80 max-sm:hidden">
          ▤
        </button>
        {isLoading ? (
          <PrimaryButton size="compact" type="button" onClick={onStop} aria-label="Stop generating" title="Stop (Esc)" className="h-full self-stretch rounded-none max-sm:w-12 max-sm:min-w-12 max-sm:px-0">
            <span className="hidden sm:inline">STOP ■</span><span className="sm:hidden">■</span>
          </PrimaryButton>
        ) : (
          <PrimaryButton size="compact" type="submit" aria-label="Send message" disabled={!input.trim()} className="h-full self-stretch rounded-none disabled:cursor-not-allowed disabled:opacity-40 max-sm:w-12 max-sm:min-w-12 max-sm:px-0">
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
