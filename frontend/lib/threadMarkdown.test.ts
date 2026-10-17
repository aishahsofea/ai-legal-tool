import { describe, expect, it } from "vitest";
import type { Citation, CurrencyLabel } from "@/lib/useQuery";
import type { Message } from "@/components/locus-workspace/types";
import { responseMarkdown, threadMarkdown, VERIFY_CAVEAT } from "./threadMarkdown";

const citation = (overrides: Partial<Citation> = {}): Citation => ({
  act_number: "574",
  act_title: "*Penal Code*",
  section_number: "302",
  pdf_url: "https://example.test/574.pdf",
  page_number: 12,
  ...overrides,
});

const assistant = (overrides: Partial<Message> = {}): Message => ({
  id: "a1",
  role: "assistant",
  content: "Murder is punishable by death.",
  createdAt: "2026-01-01T00:00:00Z",
  ...overrides,
});

const label = (overrides: Partial<CurrencyLabel> = {}): CurrencyLabel => ({
  act_number: "574",
  label: "repealed",
  detail_url: "https://example.test/repeal",
  as_of_date: "2025-03-01",
  ...overrides,
});

describe("responseMarkdown", () => {
  it("lists numbered sources and ends with the verify caveat", () => {
    const md = responseMarkdown(assistant({ citations: [citation()] }));
    expect(md).toContain("Murder is punishable by death.");
    expect(md).toContain("[1] § 302, Penal Code (Act 574), p. 12");
    expect(md.endsWith(VERIFY_CAVEAT)).toBe(true);
  });

  it("omits the page when it is null", () => {
    const md = responseMarkdown(assistant({ citations: [citation({ page_number: null })] }));
    expect(md).toContain("[1] § 302, Penal Code (Act 574)");
    expect(md).not.toContain("p. ");
  });

  it("shows the path for a schedule citation with no section number", () => {
    const md = responseMarkdown(assistant({ citations: [citation({ section_number: "", path: "sched.2/art.1" })] }));
    expect(md).toContain("[1] § sched.2/art.1,");
  });

  it("adds a notice for a repealed Act", () => {
    const md = responseMarkdown(assistant({ citations: [citation()], currency_labels: [label()] }));
    expect(md).toContain("repeal record dated 2025-03-01");
    expect(md).toContain("https://example.test/repeal");
  });

  it("adds a notice for a superseded Act", () => {
    const md = responseMarkdown(assistant({ citations: [citation()], currency_labels: [label({ label: "superseded" })] }));
    expect(md).toContain("amended since the reprint we indexed (2025-03-01)");
  });

  it("adds nothing for current_as_indexed", () => {
    const md = responseMarkdown(assistant({ citations: [citation()], currency_labels: [label({ label: "current_as_indexed" })] }));
    expect(md).not.toContain("repeal");
    expect(md).not.toContain("amended");
  });

  it("has no Sources block or caveat without citations", () => {
    const md = responseMarkdown(assistant());
    expect(md).toBe("Murder is punishable by death.");
  });

  it("leaves out commentary and receipts", () => {
    const md = responseMarkdown(assistant({
      citations: [citation({ receipt: { evidence: [{ quote: "SECRET QUOTE" }] } as unknown as Citation["receipt"] })],
      commentary: [{ url: "https://c.test", title: "COMMENTARY TITLE", publisher: "p", published_date: "", retrieved_at: "", snippet: "s" }],
    }));
    expect(md).not.toContain("SECRET QUOTE");
    expect(md).not.toContain("COMMENTARY TITLE");
  });
});

describe("threadMarkdown", () => {
  it("keeps turn order under the title", () => {
    const md = threadMarkdown("My thread", [
      { id: "u1", role: "user", content: "first question", createdAt: "" },
      assistant({ content: "first answer" }),
      { id: "u2", role: "user", content: "second question", createdAt: "" },
    ]);
    expect(md.startsWith("# My thread")).toBe(true);
    const order = ["**You:** first question", "**Locus:** first answer", "**You:** second question"].map((s) => md.indexOf(s));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it("skips an assistant placeholder with empty content", () => {
    const md = threadMarkdown("T", [
      { id: "u1", role: "user", content: "hello", createdAt: "" },
      assistant({ content: "" }),
    ]);
    expect(md).not.toContain("**Locus:**");
  });
});
