import { Mono, OutlineButton } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";

export function ConversationHeader({ title }: { title: string }) {
  return (
    <header className="conversation-header flex min-h-14 items-center justify-between gap-3 border-b border-(--line) bg-(--surface) px-4 py-2 md:px-5">
      <div className="flex min-w-0 items-baseline gap-3">
        <Mono className="conversation-header-kicker shrink-0 text-(--text-subtle)">THREAD /</Mono>
        <h1 className="truncate font-serif text-base font-light tracking-tight text-(--text)">{title}</h1>
      </div>
      <div className="conversation-header-actions flex shrink-0 items-center gap-2" role="group" aria-label="Thread actions">
        <OutlineButton className="conversation-header-secondary-action shrink-0 whitespace-nowrap" disabled title="Coming soon" aria-label="Highlights">Highlights</OutlineButton>
        <OutlineButton className="conversation-header-secondary-action shrink-0 whitespace-nowrap" disabled title="Coming soon" aria-label="Memo">Memo</OutlineButton>
        <PrimaryButton size="compact" type="button" disabled title="Coming soon" aria-label="Export thread" className="conversation-header-export shrink-0 gap-1">
          <span className="conversation-header-export-label">Export</span>
          <span className="conversation-header-export-icon" aria-hidden="true">↗</span>
        </PrimaryButton>
      </div>
    </header>
  );
}
