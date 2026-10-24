// sessionStorage, not redirectTo: a query in redirectTo would need the Supabase allowlist widened (#263).
const KEY = "locus:pending-query";

export function withQuery(path: "/workspace" | "/login", q: string | null): string {
  return q ? `${path}?q=${encodeURIComponent(q)}` : path;
}

export function stashPendingQuery(q: string | null): void {
  if (q) sessionStorage.setItem(KEY, q);
  else sessionStorage.removeItem(KEY);
}

export function takePendingQuery(): string | null {
  const q = sessionStorage.getItem(KEY);
  sessionStorage.removeItem(KEY);
  return q;
}
