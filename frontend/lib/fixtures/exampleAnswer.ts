import type { Message } from "@/components/locus-workspace/types";
import type { StoredThread } from "@/lib/threadsTransport";
// Refresh: re-capture GET /threads/<id> with the owner token after any corpus reload or re-extraction.
import thread from "./example-thread.json";

const stored = thread as StoredThread;

export const EXAMPLE_META = {
  threadId: stored.id,
  producedOn: new Date(stored.created_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }),
};

const [user, assistant] = stored.messages;

export const EXAMPLE_MESSAGES: Message[] = [
  { ...user, id: "example-user", createdAt: EXAMPLE_META.producedOn },
  { ...assistant, id: "example-assistant", createdAt: EXAMPLE_META.producedOn },
];
