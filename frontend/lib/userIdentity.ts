// Weak, per-browser practitioner identity for scoping Semantic Memory across
// research threads (see docs/adr/0010-agent-memory-lifecycle.md). There is no
// authentication in v1: the user_id is a UUID generated once and persisted in
// localStorage, sent with every /query so the backend can namespace durable
// facts by practitioner rather than by thread.

const USER_ID_KEY = "legal-assistant.user-id";
const ANONYMOUS = "anonymous";

function freshId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Return this browser's stable practitioner user_id, creating and persisting one
 * on first call. Falls back to a fixed anonymous id when localStorage is
 * unavailable (SSR, private mode) so memory scoping degrades rather than throws.
 */
export function getUserId(): string {
  if (typeof window === "undefined") return ANONYMOUS;
  try {
    const existing = window.localStorage.getItem(USER_ID_KEY);
    if (existing) return existing;
    const created = freshId();
    window.localStorage.setItem(USER_ID_KEY, created);
    return created;
  } catch {
    return ANONYMOUS;
  }
}
