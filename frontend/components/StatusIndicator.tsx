export function StatusIndicator({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 px-1">
      <span className="flex gap-0.5">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </span>
      <span>{message}</span>
    </div>
  );
}
