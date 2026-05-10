export function StatusIndicator({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="flex items-center gap-2 px-1 font-mono text-xs uppercase tracking-widest text-(--ink-3)">
      <span className="flex gap-0.5 text-(--bronze)">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-1.5 w-1.5 rounded-full bg-current" style={{ opacity: 0.45 + i * 0.18 }} />
        ))}
      </span>
      <span>{message}</span>
    </div>
  );
}
