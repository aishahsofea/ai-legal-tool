import { API_URL, type Citation, type CommentaryNote, type CurrencyLabel } from "@/lib/queryTransport";
import { authHeaders } from "@/lib/supabaseClient";

export interface ThreadListItem {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  commentary?: CommentaryNote[];
  currency_labels?: CurrencyLabel[];
}

export interface StoredThread extends ThreadListItem {
  messages: StoredMessage[];
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchThreads(): Promise<ThreadListItem[]> {
  return getJson("/threads");
}

export async function deleteThread(threadId: string): Promise<void> {
  const res = await fetch(`${API_URL}/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  // 404 means already gone, which is the outcome the caller wanted
  if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`);
}

export function fetchThread(threadId: string): Promise<StoredThread> {
  return getJson(`/threads/${encodeURIComponent(threadId)}`);
}
