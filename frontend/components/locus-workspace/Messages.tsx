import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Mono, OutlineButton } from "@/components/chamber";
import { StatusIndicator } from "@/components/StatusIndicator";
import { markdownComponents } from "./markdown";
import type { Message } from "./types";

function formatSourceTitle(title: string) {
  return title.replace(/\*/g, "").trim();
}

function scopedId(...parts: Array<string | number>) {
  return parts.join("-").replace(/[^a-zA-Z0-9_-]/g, "-");
}

function sourceMapId(messageId: string) {
  return scopedId("source-map", messageId);
}

function sourceRefId(messageId: string, citation: NonNullable<Message["citations"]>[number], index: number) {
  return `source-ref-${scopedId(messageId, citation.act_number, citation.section_number, index)}`;
}

const SOURCE_MAP_VISIBLE_LIMIT = 6;

type CitationList = NonNullable<Message["citations"]>;

function SourceMapLink({ citation, index, messageId }: { citation: CitationList[number]; index: number; messageId: string }) {
  const refId = sourceRefId(messageId, citation, index);

  return (
    <a key={refId} href={`#source-ref-${scopedId(messageId, citation.act_number, citation.section_number, index)}`} className="inline-flex items-center gap-2 rounded-sm border border-(--rule) bg-(--bg-2) px-2 py-1 text-xs text-(--ink-2) transition-colors duration-150 hover:border-(--bronze) hover:text-(--bronze)">
      <span className="font-mono text-[10px] uppercase tracking-widest text-(--bronze)">[{index + 1}]</span>
      <span className="font-serif">§ {citation.section_number}</span>
    </a>
  );
}

function InlineSourceSummary({ citations, messageId }: { citations: CitationList; messageId: string }) {
  if (citations.length === 0) return null;

  const visibleSources = citations.slice(0, SOURCE_MAP_VISIBLE_LIMIT);
  const remainingSources = citations.slice(SOURCE_MAP_VISIBLE_LIMIT);

  const mapId = sourceMapId(messageId);

  return (
    <nav id={mapId} className="chamber-max-content rounded-sm border border-(--rule-soft) bg-(--bronze-tint) px-2 py-2" aria-label="Sources cited before this answer">
      <div className="mb-2 flex items-center gap-2">
        <Mono className="text-(--bronze)">SOURCE MAP</Mono>
        <span className="font-serif text-xs italic text-(--ink-3)">cited in this answer</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {visibleSources.map((citation, index) => <SourceMapLink key={sourceRefId(messageId, citation, index)} citation={citation} index={index} messageId={messageId} />)}
      </div>
      {remainingSources.length > 0 && (
        <details className="mt-2 rounded-sm border border-(--rule-soft) bg-(--bg-2) px-2 py-1">
          <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-widest text-(--ink-3) transition-colors duration-150 hover:text-(--bronze)">
            + {remainingSources.length} more source{remainingSources.length === 1 ? "" : "s"}
          </summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {remainingSources.map((citation, index) => {
              const sourceIndex = index + SOURCE_MAP_VISIBLE_LIMIT;
              return <SourceMapLink key={sourceRefId(messageId, citation, sourceIndex)} citation={citation} index={sourceIndex} messageId={messageId} />;
            })}
          </div>
        </details>
      )}
    </nav>
  );
}

function InlineSources({ citations, messageId }: { citations: NonNullable<Message["citations"]>; messageId: string }) {
  if (citations.length === 0) return null;

  const mapId = sourceMapId(messageId);

  return (
    <section className="chamber-max-content border-t border-(--rule-soft) pt-3" aria-label="Sources used in this answer">
      <div className="mb-2 flex items-center gap-2 text-(--ink-3)">
        <Mono className="text-(--bronze)">SOURCES USED</Mono>
        <span className="h-px flex-1 bg-(--rule-soft)" />
      </div>
      <ol className="space-y-2">
        {citations.map((citation, index) => (
          <li id={sourceRefId(messageId, citation, index)} key={sourceRefId(messageId, citation, index)} className="scroll-mt-4 rounded-sm border border-(--rule) bg-(--bg-2) p-2">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-(--ink)">
              <span className="font-mono text-[10px] uppercase tracking-widest text-(--bronze)">[{index + 1}] § {citation.section_number}</span>
              <span className="font-serif font-light">{formatSourceTitle(citation.act_title)}</span>
              {citation.page_number && <span className="font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">p. {citation.page_number}</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-3">
              {citation.pdf_url && (
                <a aria-label={`Open source ${index + 1}: ${formatSourceTitle(citation.act_title)}`} className="chamber-link font-mono text-[10px] uppercase tracking-widest" href={citation.pdf_url} target="_blank" rel="noopener noreferrer">
                  Open full act ↗
                </a>
              )}
              <a className="chamber-link font-mono text-[10px] uppercase tracking-widest" href={`#${mapId}`}>
                Back to source map ↑
              </a>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ReasoningTrace({ steps, open, toggle }: { steps: string[]; open: boolean; toggle: () => void }) {
  return (
    <div className="chamber-max-content rounded-sm border border-(--rule) bg-(--bg-2)">
      <button type="button" onClick={toggle} className="flex w-full cursor-pointer items-center gap-2 px-2 py-2 text-left text-(--ink-2) transition-colors duration-150 chamber-hover-soft active:opacity-80">
        <span className="text-(--bronze)">{open ? "▾" : "▸"}</span>
        <Mono>PROCESS</Mono>
        <Mono className="ml-auto text-(--ink-3)">{steps.length} STEP{steps.length === 1 ? "" : "S"}</Mono>
      </button>
      {open && (
        <ol className="border-t border-(--rule-soft) px-2 py-2">
          {steps.map((step, index) => (
            <li key={`${step}-${index}`} className="grid chamber-grid-reason gap-2 border-b border-dotted border-(--rule-soft) py-2 last:border-b-0">
              <span className="font-mono text-[10px] uppercase tracking-wide text-(--bronze)">{String(index + 1).padStart(2, "0")}</span>
              <span className="text-xs leading-normal text-(--ink-2)">{step}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function AssistantMessage({
  message,
  citedCountLabel,
  status,
  isLoading,
  isTail,
  reasoningOpen,
  onToggleReasoning,
  statusHistory,
}: {
  message: Message;
  citedCountLabel: string;
  status: string;
  isLoading: boolean;
  isTail: boolean;
  reasoningOpen: boolean;
  onToggleReasoning: () => void;
  statusHistory: string[];
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-(--ink-3)">
        <Mono>LOCUS · {message.createdAt}</Mono>
        <span className="flex items-center gap-2 text-(--bronze)">
          <span className="h-2 w-2 rounded-full bg-(--bronze)" />
          <Mono className="text-(--bronze)">{citedCountLabel.toUpperCase()}</Mono>
        </span>
      </div>

      {(statusHistory.length > 0 || isLoading) && (
        <ReasoningTrace steps={statusHistory.length > 0 ? statusHistory : [status || "Connecting…"]} open={reasoningOpen} toggle={onToggleReasoning} />
      )}

      {message.citations && message.citations.length > 0 && <InlineSourceSummary citations={message.citations} messageId={message.id} />}

      <div className="chamber-max-content space-y-2 text-sm leading-6 text-(--ink)">
        {message.content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{message.content}</ReactMarkdown>
        ) : isLoading && isTail ? (
          <StatusIndicator message={status || "Reading sources…"} />
        ) : null}
      </div>

      {message.citations && message.citations.length > 0 && <InlineSources citations={message.citations} messageId={message.id} />}

      <div className="flex flex-wrap gap-2 border-t border-(--rule-soft) pt-4" role="group" aria-label="Message actions">
        <OutlineButton disabled title="Coming soon" aria-label="Save as memo"><span className="hidden sm:inline">Save as memo</span><span className="sm:hidden">Save</span></OutlineButton>
        <OutlineButton disabled title="Coming soon" aria-label="Highlight passage"><span className="hidden sm:inline">Highlight passage</span><span className="sm:hidden">Mark</span></OutlineButton>
        <OutlineButton disabled title="Coming soon" aria-label="Cite all"><span className="hidden sm:inline">Cite all</span><span className="sm:hidden">Cite</span></OutlineButton>
      </div>
    </div>
  );
}

export function UserMessage({ message }: { message: Message }) {
  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">YOU · {message.createdAt}</div>
      <div className="chamber-max-content-narrow border-l border-(--bronze) pl-4 font-serif text-base font-light leading-snug tracking-tight text-(--ink)">
        {message.content}
      </div>
    </div>
  );
}
