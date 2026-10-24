"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
import { AssistantMessage, UserMessage } from "@/components/conversation";
import type { Message } from "@/components/locus-workspace/types";
import type { Citation } from "@/lib/useQuery";
import { summarizeSources } from "@/lib/useResearchThreads";

const CitationReceiptViewer = dynamic(
  () => import("@/components/locus-workspace/CitationReceiptViewer").then((module) => module.CitationReceiptViewer),
  { ssr: false },
);

type ReceiptSelection = {
  citation: Citation;
  evidenceIndex: number;
  opener: HTMLElement;
};

const noop = () => {};

export function ExampleAnswer({
  meta,
  messages,
}: {
  meta: { threadId: string; producedOn: string; commit?: string };
  messages: Message[];
}) {
  const [receiptSelection, setReceiptSelection] = useState<ReceiptSelection | null>(null);

  const openReceipt = useCallback((citation: Citation, evidenceIndex: number, opener: HTMLElement) => {
    setReceiptSelection({ citation, evidenceIndex, opener });
  }, []);

  const closeReceipt = useCallback(() => {
    const opener = receiptSelection?.opener;
    setReceiptSelection(null);
    window.requestAnimationFrame(() => opener?.focus());
  }, [receiptSelection]);

  return (
    <div className="space-y-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">Saved example · produced {meta.producedOn}</p>
      {messages.map((message) =>
        message.role === "assistant" ? (
          <AssistantMessage
            key={message.id}
            message={message}
            citedCountLabel={summarizeSources(message.citations ?? [])}
            status=""
            isLoading={false}
            isTail={false}
            reasoningOpen={false}
            onToggleReasoning={noop}
            statusHistory={[]}
            nodeRuns={[]}
            onOpenReceipt={openReceipt}
          />
        ) : (
          <UserMessage key={message.id} message={message} />
        ),
      )}
      {receiptSelection && (
        <CitationReceiptViewer
          key={`${receiptSelection.citation.receipt?.document_id}:${receiptSelection.citation.section_number}:${receiptSelection.citation.path ?? ""}:${receiptSelection.evidenceIndex}`}
          citation={receiptSelection.citation}
          initialEvidenceIndex={receiptSelection.evidenceIndex}
          modal
          onClose={closeReceipt}
        />
      )}
    </div>
  );
}
