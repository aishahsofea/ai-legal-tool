import { useState } from "react";
import { Mono, OutlineButton, SourceChip } from "@/components/chamber";
import type { Citation } from "@/lib/useQuery";
import type { Message } from "./types";

function formatCitation(citation: Citation) {
  const actTitle = citation.act_title.replace(/\*/g, "").trim();
  const page = citation.page_number ? `, p. ${citation.page_number}` : "";
  return `Section ${citation.section_number}, ${actTitle} (Act ${citation.act_number})${page}`;
}

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
  const [copied, setCopied] = useState(false);

  const openFullAct = () => {
    if (!activeSource?.pdf_url) return;
    window.open(activeSource.pdf_url, "_blank", "noopener,noreferrer");
  };

  const copyCitation = async () => {
    if (!activeSource) return;
    await navigator.clipboard.writeText(formatCitation(activeSource));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <aside className="flex min-w-0 flex-col border-l border-(--rule) bg-background">
      <div className="border-b border-(--rule) px-2 pb-2 pt-4">
        <div className="font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
          SOURCES IN THIS THREAD
        </div>
        <div className="mt-2 font-serif text-base font-light tracking-tight text-foreground">
          {label}
        </div>
        <OutlineButton
          disabled
          title="Coming soon"
          className="mt-2 font-mono uppercase tracking-widest"
        >
          Filter
        </OutlineButton>
      </div>

      {activeSource ? (
        <div className="m-2 rounded-sm border border-(--bronze) bg-(--bg-2) p-2 chamber-shadow-popover">
          <div className="mb-2 flex items-center justify-between gap-2">
            <Mono className="text-(--bronze)">
              § {activeSource.section_number}
            </Mono>
            <button
              type="button"
              onClick={() => onSelectSource(-1)}
              aria-label="Clear selected source"
              className="cursor-pointer text-lg leading-none text-(--ink-3) transition-colors duration-150 hover:text-(--bronze) active:opacity-80"
            >
              ×
            </button>
          </div>
          <div className="font-serif text-sm font-light tracking-tight text-foreground">
            {activeSource.act_title.replace(/\*/g, "").trim()}
          </div>
          <div className="mt-2 font-serif text-xs italic text-(--ink-3)">
            {activeSource.page_number
              ? `Page ${activeSource.page_number}`
              : `Act ${activeSource.act_number}`}
          </div>
          <div className="mt-2 border-t border-(--rule-soft) pt-2 font-serif text-xs leading-normal text-(--ink-2)">
            {assistantMessage?.content
              ? assistantMessage.content.slice(0, 140).replace(/\s+/g, " ")
              : "The selected source appears in the current answer."}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <OutlineButton
              type="button"
              onClick={openFullAct}
              className="font-mono uppercase tracking-widest"
            >
              Open full act ↗
            </OutlineButton>
            <OutlineButton
              type="button"
              onClick={copyCitation}
              className="font-mono uppercase tracking-widest"
            >
              {copied ? "Copied" : "Copy citation"}
            </OutlineButton>
          </div>
        </div>
      ) : (
        <div className="m-2 rounded-sm border border-(--rule) bg-(--bg-2) p-2 text-xs text-(--ink-2)">
          No sources yet.
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {sources.length > 0 ? (
          sources.map((citation, index) => (
            <SourceChip
              key={`${citation.act_number}-${citation.section_number}-${index}`}
              citation={citation}
              active={index === activeSourceIndex}
              onClick={() => onSelectSource(index)}
            />
          ))
        ) : (
          <div className="px-2 py-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">
            Sources will appear here after a query.
          </div>
        )}
      </div>
    </aside>
  );
}
