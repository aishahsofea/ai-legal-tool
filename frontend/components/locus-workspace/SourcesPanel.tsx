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
    <aside className="flex min-w-0 flex-col border-l border-(--line) bg-(--surface-soft)">
      <div className="border-b border-(--line) px-3 py-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">
          SOURCES IN THIS THREAD
        </div>
        <div className="mt-2 font-serif text-base font-light tracking-tight text-(--text)">
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
        <div className="chamber-shadow-popover m-3 rounded-lg border border-(--accent-line) bg-(--surface) p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <Mono className="text-(--accent)">
              § {activeSource.section_number}
            </Mono>
            <button
              type="button"
              onClick={() => onSelectSource(-1)}
              aria-label="Clear selected source"
              className="cursor-pointer text-lg leading-none text-(--text-subtle) transition-colors duration-200 hover:text-(--accent) active:opacity-80"
            >
              ×
            </button>
          </div>
          <div className="font-serif text-sm font-light tracking-tight text-(--text)">
            {activeSource.act_title.replace(/\*/g, "").trim()}
          </div>
          <div className="mt-2 font-serif text-xs italic text-(--text-subtle)">
            {activeSource.page_number
              ? `Page ${activeSource.page_number}`
              : `Act ${activeSource.act_number}`}
          </div>
          <div className="mt-3 border-t border-(--line-soft) pt-3 font-serif text-xs leading-4 text-(--text-muted)">
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
        <div className="m-3 rounded-lg border border-(--line) bg-(--surface) p-3 text-xs text-(--text-muted)">
          No sources yet.
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {sources.length > 0 ? (
          sources.map((citation, index) => (
            <SourceChip
              key={`${citation.act_number}-${citation.section_number}`}
              citation={citation}
              active={index === activeSourceIndex}
              onClick={() => onSelectSource(index)}
            />
          ))
        ) : (
          <div className="px-3 py-3 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">
            Sources will appear here after a query.
          </div>
        )}
      </div>
    </aside>
  );
}
