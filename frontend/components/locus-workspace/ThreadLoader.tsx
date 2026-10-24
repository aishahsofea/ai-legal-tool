import { Spinner } from "@/components/icons";

export function ThreadLoader() {
  return (
    <div className="flex items-center justify-center gap-2 p-6 text-(--text-muted)">
      <Spinner />
      <p className="text-sm" role="status">Opening thread…</p>
    </div>
  );
}
