import { amendmentNotice, citationMarker, formatSourceTitle, repealWarning } from "@/components/locus-workspace/citationRefs";
import type { Message } from "@/components/locus-workspace/types";

export const VERIFY_CAVEAT = "Check each cited section against the official text published by the Attorney General's Chambers before relying on it.";

function currencyNotices({ citations = [], currency_labels = [] }: Message) {
  return currency_labels.flatMap((label) => {
    const cited = citations.find((c) => c.act_number === label.act_number);
    if (!cited) return [];
    if (label.label === "repealed") return [`${repealWarning(cited, label)} ${label.detail_url}`];
    if (label.label === "superseded") return [`${amendmentNotice(cited, label)} ${label.detail_url}`];
    return [];
  });
}

export function responseMarkdown(message: Message) {
  const citations = message.citations ?? [];
  if (citations.length === 0) return message.content;

  const sources = citations.map((c, i) => {
    const page = c.page_number === null ? "" : `, p. ${c.page_number}`;
    return `[${i + 1}] § ${citationMarker(c)}, ${formatSourceTitle(c.act_title)} (Act ${c.act_number})${page}`;
  });
  const notices = currencyNotices(message);

  return [
    message.content,
    ["**Sources**", ...sources].join("\n"),
    ...(notices.length > 0 ? [notices.join("\n\n")] : []),
    VERIFY_CAVEAT,
  ].join("\n\n");
}

export function threadMarkdown(title: string, messages: Message[]) {
  const turns = messages
    .filter((m) => m.role === "user" || m.content)
    .map((m) => (m.role === "user" ? `**You:** ${m.content}` : `**Locus:** ${responseMarkdown(m)}`));
  return [`# ${title}`, ...turns].join("\n\n");
}
