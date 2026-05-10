import type { Citation } from "@/lib/useQuery";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  createdAt: string;
};

export type ThreadSummary = {
  id: string;
  title: string;
  meta: string;
  active: boolean;
};
