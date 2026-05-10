import { Mark, ThreadRow } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";
import type { ThreadSummary } from "./types";

export function ThreadSidebar({
  threads,
  onNewThread,
  onSelectThread,
  userName,
  userFirm,
  switchingDisabled = false,
}: {
  threads: ThreadSummary[];
  onNewThread: () => void;
  onSelectThread: (threadId: string) => void;
  userName: string;
  userFirm: string;
  switchingDisabled?: boolean;
}) {
  return (
    <aside className="flex w-full flex-col overflow-hidden border-r border-(--rule) bg-(--bg) md:w-14 xl:w-full" aria-label="Threads">
      <div className="border-b border-(--rule) px-2 pb-2 pt-4">
        <div className="flex justify-center xl:justify-start"><Mark /></div>
        <PrimaryButton onClick={onNewThread} leading="＋" title="New thread" aria-label="New thread" className="mt-2 flex w-full items-center justify-center gap-2">
          <span className="hidden xl:inline">New thread</span>
        </PrimaryButton>
      </div>

      <div className="flex flex-1 flex-col gap-2 px-2 py-2">
        {threads.length > 0 ? (
          threads.map((thread) => (
            <ThreadRow
              key={thread.id}
              title={thread.title}
              meta={thread.meta}
              active={thread.active}
              disabled={switchingDisabled && !thread.active}
              onClick={() => onSelectThread(thread.id)}
            />
          ))
        ) : (
          <div className="px-2 py-2 text-center font-mono text-[10px] uppercase tracking-widest text-(--ink-3)" title="No threads yet">
            <span className="xl:hidden">—</span>
            <span className="hidden xl:block">No threads yet</span>
          </div>
        )}
      </div>

      <div className="mt-auto flex items-center justify-center gap-2 border-t border-(--rule) px-2 py-2 xl:justify-start" title={`${userName} · ${userFirm}`}>
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-(--bronze) text-xs font-semibold text-(--bg)">
          {userName.slice(0, 2).toUpperCase()}
        </div>
        <div className="hidden xl:block min-w-0">
          <div className="truncate text-xs text-(--ink)">{userName}</div>
          <div className="mt-2 truncate font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">{userFirm}</div>
        </div>
      </div>
    </aside>
  );
}
