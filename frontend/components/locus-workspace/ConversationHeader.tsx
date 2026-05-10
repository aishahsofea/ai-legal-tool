import { Mono, OutlineButton } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";

export function ConversationHeader({ title }: { title: string }) {
  return (
    <header className="flex items-center justify-between gap-2 border-b border-(--rule) px-4 py-2 lg:px-6">
      <div className="flex min-w-0 items-baseline gap-2">
        <Mono className="text-(--ink-3)">THREAD /</Mono>
        <h1 className="truncate font-serif text-base font-light tracking-tight text-(--ink)">{title}</h1>
      </div>
      <div className="flex items-center gap-2">
        <OutlineButton disabled title="Coming soon">Highlights</OutlineButton>
        <OutlineButton disabled title="Coming soon">Memo</OutlineButton>
        <PrimaryButton type="button" disabled title="Coming soon" className="px-2 py-2 text-xs">Export ↗</PrimaryButton>
      </div>
    </header>
  );
}
