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
    <aside className="flex min-h-0 min-w-0 flex-col border-r border-(--line) bg-(--surface-soft) max-md:max-h-[168px] max-md:border-b max-md:border-r-0">
      <div className="border-b border-(--line) px-3 py-3 max-md:flex max-md:items-center max-md:justify-between max-md:gap-3">
        <Mark />
        <PrimaryButton onClick={onNewThread} leading="＋" className="mt-3 flex w-full items-center justify-center gap-2 max-md:mt-0 max-md:w-auto">
          New thread
        </PrimaryButton>
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto px-2 py-2 max-md:flex-row max-md:overflow-x-auto max-md:overflow-y-hidden">
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
          <div className="px-3 py-3 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">No threads yet</div>
        )}
      </div>

      <div className="mt-auto flex items-center gap-3 border-t border-(--line) px-3 py-3 max-md:hidden">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-(--accent) text-xs font-semibold text-(--surface)">
          {userName.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <div className="text-sm text-(--text)">{userName}</div>
          <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-(--text-subtle)">{userFirm}</div>
        </div>
      </div>
    </aside>
  );
}
