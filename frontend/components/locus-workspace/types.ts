import type { Citation, CommentaryNote, CurrencyLabel } from "@/lib/useQuery";

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  commentary?: CommentaryNote[];
  currency_labels?: CurrencyLabel[];
  createdAt: string;
};

export type ThreadSummary = {
  id: string;
  title: string;
  meta: string;
  active: boolean;
};
