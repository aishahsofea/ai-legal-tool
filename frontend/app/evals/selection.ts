// Selection can hold ids a filter currently hides, and runs still use them.
// So every helper reads only `shownIds` for display state and leaves hidden ids alone.

export type HeaderState = "all" | "some" | "none";

// A missing or filtered-out anchor means "no range": fall back to one toggle
// instead of guessing a range over rows the user can't see.
export function selectRange(
  shownIds: string[],
  selected: Set<string>,
  anchorId: string | null,
  clickedId: string,
  checked: boolean,
): Set<string> {
  const next = new Set(selected);
  const anchor = anchorId === null ? -1 : shownIds.indexOf(anchorId);
  const clicked = shownIds.indexOf(clickedId);
  const ids = anchor === -1 || clicked === -1
    ? [clickedId]
    : shownIds.slice(Math.min(anchor, clicked), Math.max(anchor, clicked) + 1);
  for (const id of ids) {
    if (checked) next.add(id);
    else next.delete(id);
  }
  return next;
}

export function headerState(shownIds: string[], selected: Set<string>): HeaderState {
  const count = shownIds.filter((id) => selected.has(id)).length;
  if (count === 0) return "none";
  return count === shownIds.length ? "all" : "some";
}

export function toggleShown(shownIds: string[], selected: Set<string>): Set<string> {
  const next = new Set(selected);
  const clear = headerState(shownIds, selected) === "all";
  for (const id of shownIds) {
    if (clear) next.delete(id);
    else next.add(id);
  }
  return next;
}
