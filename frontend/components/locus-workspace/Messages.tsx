import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Mono, OutlineButton } from "@/components/chamber";
import { StatusIndicator } from "@/components/StatusIndicator";
import { createMarkdownComponents } from "./markdown";
import { formatSourceTitle, scopedId, sourceMapId, sourceRefId } from "./citationRefs";
import { rehypeCitationLinks } from "./rehypeCitationLinks";
import type { Message } from "./types";
import type { Citation, NodeRun } from "@/lib/useQuery";

const SOURCE_MAP_VISIBLE_LIMIT = 6;

type CitationList = NonNullable<Message["citations"]>;
type OpenReceipt = (citation: Citation, evidenceIndex: number, opener: HTMLElement) => void;

function SourceMapLink({ citation, index, messageId }: { citation: CitationList[number]; index: number; messageId: string }) {
  const refId = sourceRefId(messageId, citation, index);

  return (
    <a key={refId} href={`#source-ref-${scopedId(messageId, citation.act_number, citation.section_number, index)}`} className="inline-flex min-h-8 items-center gap-2 rounded-lg border border-(--line) bg-(--surface) px-3 py-1 text-xs text-(--text-muted) transition-colors duration-200 hover:border-(--accent-line) hover:bg-(--accent-tint) hover:text-(--accent)">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--accent)">[{index + 1}]</span>
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
    <nav id={mapId} className="chamber-max-content rounded-lg border border-(--accent-line) bg-(--accent-tint) px-3 py-3" aria-label="Sources cited before this answer">
      <div className="mb-2 flex items-center gap-2">
        <Mono className="text-(--accent)">SOURCE MAP</Mono>
        <span className="font-serif text-xs italic text-(--text-subtle)">cited in this answer</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {visibleSources.map((citation, index) => <SourceMapLink key={sourceRefId(messageId, citation, index)} citation={citation} index={index} messageId={messageId} />)}
      </div>
      {remainingSources.length > 0 && (
        <details className="mt-2 rounded-lg border border-(--line-soft) bg-(--surface) px-3 py-2">
          <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle) transition-colors duration-200 hover:text-(--accent)">
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

function InlineSources({ citations, messageId, onOpenReceipt }: { citations: NonNullable<Message["citations"]>; messageId: string; onOpenReceipt: OpenReceipt }) {
  if (citations.length === 0) return null;

  const mapId = sourceMapId(messageId);

  return (
    <section className="chamber-max-content border-t border-(--line-soft) pt-4" aria-label="Sources used in this answer">
      <div className="mb-3 flex items-center gap-2 text-(--text-subtle)">
        <Mono className="text-(--accent)">SOURCES USED</Mono>
        <span className="h-px flex-1 bg-(--line-soft)" />
      </div>
      <ol className="space-y-2">
        {citations.map((citation, index) => (
          <li id={sourceRefId(messageId, citation, index)} key={sourceRefId(messageId, citation, index)} className="scroll-mt-4 rounded-lg border border-(--line) bg-(--surface) p-3 shadow-[var(--shadow-soft)]">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm text-(--text)">
              <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--accent)">[{index + 1}] § {citation.section_number}</span>
              <span className="font-serif font-light">{formatSourceTitle(citation.act_title)}</span>
              {citation.page_number && <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">p. {citation.page_number}</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-3">
              {citation.receipt ? (
                <button
                  type="button"
                  aria-label={`Open Citation Receipt ${index + 1}: ${formatSourceTitle(citation.act_title)}`}
                  className="chamber-link font-mono text-[10px] uppercase tracking-[0.12em]"
                  onClick={(event) => onOpenReceipt(citation, 0, event.currentTarget)}
                >
                  Open citation receipt
                </button>
              ) : citation.pdf_url ? (
                <a aria-label={`Open source ${index + 1}: ${formatSourceTitle(citation.act_title)}`} className="chamber-link font-mono text-[10px] uppercase tracking-[0.12em]" href={citation.pdf_url} target="_blank" rel="noopener noreferrer">
                  Open full act ↗
                </a>
              ) : null}
              <a className="chamber-link font-mono text-[10px] uppercase tracking-[0.12em]" href={`#${mapId}`}>
                Back to source map ↑
              </a>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function CommentaryNotes({ commentary }: { commentary: NonNullable<Message["commentary"]> }) {
  if (commentary.length === 0) return null;

  return (
    <section className="chamber-max-content border-t border-dashed border-(--line) pt-4" aria-label="Background commentary, not a legal citation">
      <div className="mb-3 flex items-center gap-2 text-(--text-subtle)">
        <Mono className="text-(--text-muted)">COMMENTARY</Mono>
        <span className="font-serif text-xs italic text-(--text-subtle)">background reading, not cited as authority</span>
        <span className="h-px flex-1 bg-(--line-soft)" />
      </div>
      <ol className="space-y-2">
        {commentary.map((note, index) => (
          <li key={`${note.url}-${index}`} className="rounded-lg border border-dashed border-(--line) bg-(--surface-soft) p-3">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-(--text-subtle)">
              <span className="font-mono text-[10px] uppercase tracking-[0.12em]">{note.publisher}</span>
              {note.published_date && <span className="font-mono text-[10px] uppercase tracking-[0.12em]">{note.published_date}</span>}
            </div>
            <div className="mt-1 font-serif font-light text-(--text)">{note.title}</div>
            {note.snippet && <p className="mt-1 text-xs leading-5 text-(--text-muted)">{note.snippet}</p>}
            <a
              aria-label={`Open publisher site: ${note.title}`}
              className="chamber-link mt-2 inline-block font-mono text-[10px] uppercase tracking-[0.12em]"
              href={note.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open publisher site ↗
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}

function formatDuration(ms: number) {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function ReasoningTrace({ steps, nodeRuns, open, toggle }: { steps: string[]; nodeRuns: NodeRun[]; open: boolean; toggle: () => void }) {
  return (
    <div className="chamber-max-content overflow-hidden rounded-lg border border-(--line) bg-(--surface)">
      <button type="button" onClick={toggle} className="chamber-hover-soft flex min-h-10 w-full cursor-pointer items-center gap-2 px-4 py-2 text-left text-(--text-muted) transition-colors duration-200 active:opacity-80">
        <span className="text-(--accent)">{open ? "▾" : "▸"}</span>
        <Mono>PROCESS</Mono>
        <Mono className="ml-auto text-(--text-subtle)">{steps.length} STEP{steps.length === 1 ? "" : "S"}</Mono>
      </button>
      {open && (
        <ol className="border-t border-(--line-soft) px-4 py-2">
          {steps.map((step, index) => (
            <li key={`${step}-${index}`} className="chamber-grid-reason grid gap-2 border-b border-dotted border-(--line-soft) py-3 last:border-b-0">
              <span className="font-mono text-[10px] uppercase tracking-wide text-(--accent)">{String(index + 1).padStart(2, "0")}</span>
              <span className="text-xs leading-4 text-(--text-muted)">{step}</span>
            </li>
          ))}
        </ol>
      )}
      {/* Below the steps, and counted separately: the collapsed header reports
          STEPS, and model rows must not inflate that number. */}
      {open && nodeRuns.length > 0 && (
        <ol className="border-t border-(--line-soft) px-4 py-2">
          <li className="pb-2">
            <Mono className="text-(--text-subtle)">MODELS</Mono>
          </li>
          {/* Stacked, not chamber-grid-reason: that grid's first column is 24px,
              sized for a two-digit step number. A node name ("grounding_check")
              overruns it straight into the model id. */}
          {nodeRuns.map((run, index) => (
            <li key={`${run.name}-${index}`} className="border-b border-dotted border-(--line-soft) py-3 last:border-b-0">
              <div className="font-mono text-[10px] uppercase tracking-wide text-(--accent)">{run.name}</div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs leading-4 text-(--text-muted)">
                <span className="break-all">{run.model}</span>
                <span className="text-(--text-subtle)">{formatDuration(run.duration_ms)}</span>
              </div>
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
  nodeRuns,
  onOpenReceipt,
}: {
  message: Message;
  citedCountLabel: string;
  status: string;
  isLoading: boolean;
  isTail: boolean;
  reasoningOpen: boolean;
  onToggleReasoning: () => void;
  statusHistory: string[];
  nodeRuns: NodeRun[];
  onOpenReceipt: OpenReceipt;
}) {
  return (
    <article className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-(--text-subtle)">
        <Mono>LOCUS · {message.createdAt}</Mono>
        <span className="flex items-center gap-2 text-(--accent)">
          <span className="h-2 w-2 rounded-full bg-(--accent)" />
          <Mono className="text-(--accent)">{citedCountLabel.toUpperCase()}</Mono>
        </span>
      </div>

      {!(isLoading && isTail) && (statusHistory.length > 0 || nodeRuns.length > 0) && (
        <ReasoningTrace steps={statusHistory} nodeRuns={nodeRuns} open={reasoningOpen} toggle={onToggleReasoning} />
      )}

      {message.citations && message.citations.length > 0 && <InlineSourceSummary citations={message.citations} messageId={message.id} />}

      <div className="chamber-max-content chamber-reading-flow space-y-3 text-sm leading-6 text-(--text)">
        {message.content ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[[rehypeCitationLinks, { citations: message.citations ?? [] }]]}
            components={createMarkdownComponents(message.citations ?? [], onOpenReceipt)}
          >
            {message.content}
          </ReactMarkdown>
        ) : isLoading && isTail ? (
          <StatusIndicator message={status || "Reading sources…"} />
        ) : null}
      </div>

      {message.citations && message.citations.length > 0 && <InlineSources citations={message.citations} messageId={message.id} onOpenReceipt={onOpenReceipt} />}

      {message.commentary && message.commentary.length > 0 && <CommentaryNotes commentary={message.commentary} />}

      <div className="flex flex-wrap gap-2 border-t border-(--line-soft) pt-4" role="group" aria-label="Message actions">
        <OutlineButton disabled title="Coming soon" aria-label="Save as memo"><span className="hidden sm:inline">Save as memo</span><span className="sm:hidden">Save</span></OutlineButton>
        <OutlineButton disabled title="Coming soon" aria-label="Highlight passage"><span className="hidden sm:inline">Highlight passage</span><span className="sm:hidden">Mark</span></OutlineButton>
        <OutlineButton disabled title="Coming soon" aria-label="Cite all"><span className="hidden sm:inline">Cite all</span><span className="sm:hidden">Cite</span></OutlineButton>
      </div>
    </article>
  );
}

export function UserMessage({ message }: { message: Message }) {
  return (
    <article className="flex w-full justify-end">
      <div className="flex max-w-[640px] flex-col items-end gap-2 sm:max-w-[72%]">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">YOU · {message.createdAt}</div>
        <div className="rounded-xl border border-(--accent-line) bg-(--accent-soft) px-3 py-2 font-serif text-sm font-light leading-6 tracking-tight text-(--text) shadow-[var(--shadow-soft)]">
          <span className="whitespace-pre-wrap">{message.content}</span>
        </div>
      </div>
    </article>
  );
}
