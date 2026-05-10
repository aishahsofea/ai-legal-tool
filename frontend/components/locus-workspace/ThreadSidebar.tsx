import { Mark, ThreadRow } from "@/components/chamber";
import { PrimaryButton } from "@/components/PrimaryButton";
import type { ThreadSummary } from "./types";

export function ThreadSidebar({
  threads,
  onNewThread,
  userName,
  userFirm,
}: {
  threads: ThreadSummary[];
  onNewThread: () => void;
  userName: string;
  userFirm: string;
}) {
  return (
    <aside className="flex flex-col border-r border-(--rule) bg-(--bg)">
      <div className="border-b border-(--rule) px-2 pb-2 pt-4">
        <Mark />
        <PrimaryButton onClick={onNewThread} leading="＋" className="mt-2 flex w-full items-center justify-center gap-2">
          New thread
        </PrimaryButton>
      </div>

      <div className="flex flex-1 flex-col gap-2 px-2 py-2">
        {threads.length > 0 ? (
          threads.map((thread) => <ThreadRow key={thread.id} title={thread.title} meta={thread.meta} active={thread.active} />)
        ) : (
          <div className="px-2 py-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">No threads yet</div>
        )}
      </div>

      <div className="mt-auto flex items-center gap-2 border-t border-(--rule) px-2 py-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-(--bronze) text-xs font-semibold text-(--bg)">
          {userName.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <div className="text-xs text-(--ink)">{userName}</div>
          <div className="mt-2 font-mono text-[10px] uppercase tracking-widest text-(--ink-3)">{userFirm}</div>
        </div>
      </div>
    </aside>
  );
}
