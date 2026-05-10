import { Mono, OutlineButton, SourceChip } from "@/components/chamber";
import type { Citation } from "@/lib/useQuery";
import type { Message } from "./types";

export function SourcesPanel({
  label,
  activeSource,
  assistantMessage,
  onSelectSource,
  sources,
  activeSourceIndex,
}: {
  label: string;
  activeSource: Citation | null;
  assistantMessage?: Message;
  onSelectSource: (index: number) => void;
  sources: Citation[];
  activeSourceIndex: number;
}) {
  return (
    <aside className="flex min-w-0 flex-col border-l border-(--rule) bg-(--bg)">
      <div className="border-b border-(--rule) px-4 pb-4 pt-5">
        <div className="font-mono text-xs uppercase tracking-widest text-(--ink-3)">SOURCES IN THIS THREAD</div>
        <div className="mt-1 font-serif text-lg font-light tracking-tight text-(--ink)">{label}</div>
        <OutlineButton className="mt-3 font-mono text-xs uppercase tracking-widest">Filter</OutlineButton>
      </div>

      {activeSource ? (
        <div className="m-4 rounded-sm border border-(--bronze) bg-(--bg-2) p-4 chamber-shadow-popover">
          <div className="mb-2 flex items-center justify-between gap-3">
            <Mono className="text-(--bronze)">§ {activeSource.section_number}</Mono>
            <button type="button" className="text-lg leading-none text-(--ink-3)">×</button>
          </div>
          <div className="font-serif text-base font-light tracking-tight text-(--ink)">{activeSource.act_title.replace(/\*/g, "").trim()}</div>
          <div className="mt-1 font-serif text-sm italic text-(--ink-3)">{activeSource.page_number ? `Page ${activeSource.page_number}` : `Act ${activeSource.act_number}`}</div>
          <div className="mt-3 border-t border-(--rule-soft) pt-3 font-serif text-sm leading-normal text-(--ink-2)">
            {assistantMessage?.content ? assistantMessage.content.slice(0, 140).replace(/\s+/g, " ") : "The selected source appears in the current answer."}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <OutlineButton className="font-mono text-xs uppercase tracking-widest">Open full act</OutlineButton>
            <OutlineButton className="font-mono text-xs uppercase tracking-widest">Copy citation</OutlineButton>
          </div>
        </div>
      ) : (
        <div className="m-4 rounded-sm border border-(--rule) bg-(--bg-2) p-4 text-sm text-(--ink-2)">No sources yet.</div>
      )}

      <div className="flex-1 overflow-y-auto">
        {sources.length > 0 ? (
          sources.map((citation, index) => (
            <SourceChip key={`${citation.act_number}-${citation.section_number}-${index}`} citation={citation} active={index === activeSourceIndex} onClick={() => onSelectSource(index)} />
          ))
        ) : (
          <div className="px-4 py-3 font-mono text-xs uppercase tracking-widest text-(--ink-3)">Sources will appear here after a query.</div>
        )}
      </div>
    </aside>
  );
}
