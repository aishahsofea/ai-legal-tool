import { Mono, OutlineButton } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";

export function ConversationHeader({ title }: { title: string }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-(--rule) px-6 py-4 lg:px-8">
      <div className="flex min-w-0 items-baseline gap-3">
        <Mono className="text-(--ink-3)">THREAD /</Mono>
        <h1 className="truncate font-serif text-lg font-light tracking-tight text-(--ink)">{title}</h1>
      </div>
      <div className="flex items-center gap-1">
        <OutlineButton>Highlights</OutlineButton>
        <OutlineButton>Memo</OutlineButton>
        <PrimaryButton type="button" className="px-3 py-2 text-sm">Export ↗</PrimaryButton>
      </div>
    </header>
  );
}
