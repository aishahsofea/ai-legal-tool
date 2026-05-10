import ReactMarkdown from "react-markdown";
import { CitationCard } from "@/components/CitationCard";
import { Mono, OutlineButton } from "@/components/chamber";
import { StatusIndicator } from "@/components/StatusIndicator";
import { markdownComponents } from "./markdown";
import type { Message } from "./types";

function ReasoningTrace({ steps, open, toggle }: { steps: string[]; open: boolean; toggle: () => void }) {
  return (
    <div className="chamber-max-content rounded-sm border border-(--rule) bg-(--bg-2)">
      <button type="button" onClick={toggle} className="flex w-full items-center gap-3 px-4 py-3 text-left text-(--ink-2) transition-colors duration-150 chamber-hover-soft">
        <span className="text-(--bronze)">{open ? "▾" : "▸"}</span>
        <Mono>PROCESS</Mono>
        <Mono className="ml-auto text-(--ink-3)">{steps.length} STEP{steps.length === 1 ? "" : "S"}</Mono>
      </button>
      {open && (
        <ol className="border-t border-(--rule-soft) px-4 py-2">
          {steps.map((step, index) => (
            <li key={`${step}-${index}`} className="grid chamber-grid-reason gap-3 border-b border-dotted border-(--rule-soft) py-2 last:border-b-0">
              <span className="font-mono text-xs uppercase tracking-wide text-(--bronze)">{String(index + 1).padStart(2, "0")}</span>
              <span className="text-sm leading-normal text-(--ink-2)">{step}</span>
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
    <div className="space-y-4">
      <div className="flex items-center gap-3 text-(--ink-3)">
        <Mono>LOCUS · {message.createdAt}</Mono>
        <span className="flex items-center gap-2 text-(--bronze)">
          <span className="h-1.5 w-1.5 rounded-full bg-(--bronze)" />
          <Mono className="text-(--bronze)">{citedCountLabel.toUpperCase()}</Mono>
        </span>
      </div>

      {(statusHistory.length > 0 || isLoading) && (
        <ReasoningTrace steps={statusHistory.length > 0 ? statusHistory : [status || "Connecting…"]} open={reasoningOpen} toggle={onToggleReasoning} />
      )}

      <div className="chamber-max-content space-y-4 text-base leading-7 text-(--ink)">
        {message.content ? (
          <ReactMarkdown components={markdownComponents}>{message.content}</ReactMarkdown>
        ) : isLoading && isTail ? (
          <StatusIndicator message={status || "Reading sources…"} />
        ) : null}
      </div>

      {message.citations && message.citations.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {message.citations.map((citation) => <CitationCard key={`${citation.act_number}-${citation.section_number}`} citation={citation} />)}
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-(--rule-soft) pt-4">
        <OutlineButton>Save as memo</OutlineButton>
        <OutlineButton>Highlight passage</OutlineButton>
        <OutlineButton>Cite all</OutlineButton>
      </div>
    </div>
  );
}

export function UserMessage({ message }: { message: Message }) {
  return (
    <div className="space-y-3">
      <div className="font-mono text-xs uppercase tracking-widest text-(--ink-3)">YOU · {message.createdAt}</div>
      <div className="chamber-max-content-narrow border-l border-(--bronze) pl-5 font-serif text-xl font-light leading-snug tracking-tight text-(--ink)">
        {message.content}
      </div>
    </div>
  );
}
