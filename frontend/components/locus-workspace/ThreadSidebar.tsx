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
      <div className="border-b border-(--rule) px-4 pb-4 pt-6">
        <Mark />
        <PrimaryButton onClick={onNewThread} leading="＋" className="mt-4 flex w-full items-center justify-center gap-2">
          New thread
        </PrimaryButton>
      </div>

      <div className="flex flex-1 flex-col gap-1 px-3 py-4">
        {threads.length > 0 ? (
          threads.map((thread) => <ThreadRow key={thread.id} title={thread.title} meta={thread.meta} active={thread.active} />)
        ) : (
          <div className="px-2 py-3 font-mono text-xs uppercase tracking-widest text-(--ink-3)">No threads yet</div>
        )}
      </div>

      <div className="mt-auto flex items-center gap-3 border-t border-(--rule) px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-(--bronze) text-sm font-semibold text-(--bg)">
          {userName.slice(0, 2).toUpperCase()}
        </div>
        <div>
          <div className="text-sm text-(--ink)">{userName}</div>
          <div className="mt-0.5 font-mono text-xs uppercase tracking-widest text-(--ink-3)">{userFirm}</div>
        </div>
      </div>
    </aside>
  );
}
