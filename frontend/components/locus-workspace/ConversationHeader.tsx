import { IconButton, Mono } from "@/components/chamber";
import { Check, PanelLeft, Share } from "@/components/icons";
import { threadMarkdown } from "@/lib/threadMarkdown";
import { useShareText } from "@/lib/useShareText";
import type { Message } from "./types";

type Props = {
  title: string;
  messages?: Message[];
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
};

export function ConversationHeader({ title, messages = [], sidebarCollapsed = false, onToggleSidebar }: Props) {
  const { copied, share } = useShareText();
  const hasContent = messages.some((m) => m.content);

  return (
    <header className="conversation-header flex min-h-14 items-center justify-between gap-3 border-b border-(--line) bg-(--surface) px-4 py-2 md:px-5">
      <div className="flex min-w-0 items-baseline gap-3">
        {onToggleSidebar && (
          <IconButton
            type="button"
            onClick={onToggleSidebar}
            aria-controls="workspace-thread-sidebar"
            aria-expanded={!sidebarCollapsed}
            aria-label={sidebarCollapsed ? "Show thread list" : "Hide thread list"}
            title={sidebarCollapsed ? "Show thread list" : "Hide thread list"}
            className="conversation-header-sidebar-toggle self-center max-md:hidden"
          >
            <PanelLeft />
          </IconButton>
        )}
        <Mono className="conversation-header-kicker shrink-0 text-(--text-subtle)">THREAD /</Mono>
        <h1 className="truncate font-serif text-base font-light tracking-tight text-(--text)">{title}</h1>
      </div>
      <div className="conversation-header-actions flex shrink-0 items-center gap-2" role="group" aria-label="Thread actions">
        <IconButton
          type="button"
          disabled={!hasContent}
          onClick={() => void share(title, threadMarkdown(title, messages))}
          aria-label="Share thread"
          title={copied ? "Copied" : "Share thread"}
        >
          {copied ? <Check /> : <Share />}
          <span className="sr-only" aria-live="polite">{copied ? "Copied" : ""}</span>
        </IconButton>
      </div>
    </header>
  );
}
