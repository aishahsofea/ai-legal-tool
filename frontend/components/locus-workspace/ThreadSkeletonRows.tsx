export function ThreadSkeletonRows() {
  return (
    <div role="status" aria-label="Loading threads" className="flex flex-col gap-2 max-md:flex-row">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex w-full items-stretch gap-2 rounded-lg px-3 py-2 motion-safe:animate-pulse max-md:min-w-[224px]">
          <span className="w-[2px] shrink-0 rounded-full bg-transparent" />
          <div className="min-w-0 flex-1">
            <div className="h-5 w-4/5 rounded bg-(--surface-strong)" />
            <div className="mt-1 h-3 w-1/3 rounded bg-(--surface-strong)" />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading threads</span>
    </div>
  );
}
