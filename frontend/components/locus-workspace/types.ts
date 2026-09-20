import type { Citation, CommentaryNote } from "@/lib/useQuery";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  commentary?: CommentaryNote[];
  createdAt: string;
};

export type ThreadSummary = {
  id: string;
  title: string;
  meta: string;
  active: boolean;
};
