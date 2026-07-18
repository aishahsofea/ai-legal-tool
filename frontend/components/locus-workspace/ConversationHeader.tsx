import { Mono, OutlineButton } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";

export function ConversationHeader({ title }: { title: string }) {
  return (
    <header className="flex min-h-14 items-center justify-between gap-3 border-b border-(--line) bg-(--surface) px-4 py-2 md:px-5">
      <div className="flex min-w-0 items-baseline gap-3">
        <Mono className="text-(--text-subtle)">THREAD /</Mono>
        <h1 className="truncate font-serif text-base font-light tracking-tight text-(--text)">{title}</h1>
      </div>
      <div className="hidden items-center gap-2 sm:flex" role="group" aria-label="Thread actions">
        <OutlineButton disabled title="Coming soon" aria-label="Highlights"><span className="hidden sm:inline">Highlights</span></OutlineButton>
        <OutlineButton disabled title="Coming soon" aria-label="Memo"><span className="hidden sm:inline">Memo</span></OutlineButton>
        <PrimaryButton type="button" disabled title="Coming soon" aria-label="Export thread" className="px-3 py-2 text-xs"><span className="hidden sm:inline">Export ↗</span></PrimaryButton>
      </div>
    </header>
  );
}
