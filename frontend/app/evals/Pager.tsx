import { palette } from "./palette";

const BTN = "rounded-full px-3 py-1 text-xs font-semibold disabled:opacity-45";

export function Pager({
  page,
  pageCount,
  total,
  pageSize,
  label,
  onPage,
}: {
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  label: string;
  onPage: (page: number) => void;
}) {
  const first = page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  return (
    <nav aria-label={label} className="flex flex-wrap items-center justify-between gap-2">
      <span className="font-mono text-xs font-semibold" style={{ color: palette.muted }}>
        {first}–{last} of {total}
      </span>
      <div className="flex items-center gap-1.5">
        <button type="button" onClick={() => onPage(0)} disabled={page === 0} className={BTN} style={{ background: palette.panel }} aria-label="First page">«</button>
        <button type="button" onClick={() => onPage(page - 1)} disabled={page === 0} className={BTN} style={{ background: palette.panel }}>Prev</button>
        <span className="px-1 font-mono text-xs font-semibold" aria-current="page">{page + 1} / {pageCount}</span>
        <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pageCount - 1} className={BTN} style={{ background: palette.panel }}>Next</button>
        <button type="button" onClick={() => onPage(pageCount - 1)} disabled={page >= pageCount - 1} className={BTN} style={{ background: palette.panel }} aria-label="Last page">»</button>
      </div>
    </nav>
  );
}
