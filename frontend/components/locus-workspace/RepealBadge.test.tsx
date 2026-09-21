import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CurrencyLabel } from "@/lib/useQuery";
import type { Message } from "./types";
import { AssistantMessage } from "./Messages";

vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

const REPEALED_CITATION: NonNullable<Message["citations"]>[number] = {
  act_number: "762",
  act_title: "GOODS AND SERVICES TAX ACT 2014",
  section_number: "9",
  pdf_url: "https://example.com/act762.pdf",
  page_number: 4,
};

const CURRENT_CITATION: NonNullable<Message["citations"]>[number] = {
  act_number: "56",
  act_title: "Evidence Act 1950",
  section_number: "90A",
  pdf_url: "https://example.com/act56.pdf",
  page_number: 12,
};

const REPEALED_LABEL: CurrencyLabel = {
  act_number: "762",
  label: "repealed",
  detail_url: "https://example.com/act762-repealed-notice.pdf",
  as_of_date: "06/01/2018",
};

const UNKNOWN_LABEL: CurrencyLabel = {
  act_number: "56",
  label: "unknown",
  detail_url: "",
  as_of_date: "",
};

const SUPERSEDED_CITATION: NonNullable<Message["citations"]>[number] = {
  act_number: "155",
  act_title: "IMMIGRATION ACT 1959/63",
  section_number: "6",
  pdf_url: "https://example.com/act155.pdf",
  page_number: 2,
};

const SUPERSEDED_LABEL: CurrencyLabel = {
  act_number: "155",
  label: "superseded",
  detail_url: "https://example.com/act155-amendment.pdf",
  as_of_date: "26/04/2026",
};

const CURRENT_AS_INDEXED_LABEL: CurrencyLabel = {
  act_number: "56",
  label: "current_as_indexed",
  detail_url: "",
  as_of_date: "",
};

function renderMessage({
  citations = [],
  currency_labels = [],
}: { citations?: Message["citations"]; currency_labels?: Message["currency_labels"] }) {
  return render(
    <AssistantMessage
      message={{
        id: "m1",
        role: "assistant",
        content: "Section 9 applies.",
        createdAt: "10:30",
        citations,
        currency_labels,
      }}
      citedCountLabel="0 sources"
      status=""
      isLoading={false}
      isTail
      reasoningOpen={false}
      onToggleReasoning={() => {}}
      statusHistory={[]}
      nodeRuns={[]}
      onOpenReceipt={() => {}}
    />,
  );
}

afterEach(cleanup);

describe("repeal badge", () => {
  it("renders no badge when there are no currency labels", () => {
    renderMessage({ citations: [REPEALED_CITATION] });
    expect(screen.queryByText(/act repealed/i)).toBeNull();
  });

  it("renders no badge for an unknown label", () => {
    renderMessage({ citations: [CURRENT_CITATION], currency_labels: [UNKNOWN_LABEL] });
    expect(screen.queryByText(/act repealed/i)).toBeNull();
  });

  it("shows the badge only on the citation for the repealed Act", () => {
    renderMessage({
      citations: [REPEALED_CITATION, CURRENT_CITATION],
      currency_labels: [REPEALED_LABEL, UNKNOWN_LABEL],
    });

    expect(screen.getAllByText(/act repealed/i)).toHaveLength(1);
  });

  it("shows the Act number and repeal date in the visible badge text", () => {
    renderMessage({ citations: [REPEALED_CITATION], currency_labels: [REPEALED_LABEL] });
    expect(screen.getByText("⚠ Act repealed 06/01/2018")).toBeTruthy();
  });

  it("links to the repeal record, not the Act's own PDF", () => {
    renderMessage({ citations: [REPEALED_CITATION], currency_labels: [REPEALED_LABEL] });

    const badge = screen.getByRole("link", { name: /warning:/i });
    expect(badge.getAttribute("href")).toBe(REPEALED_LABEL.detail_url);
    expect(badge.getAttribute("target")).toBe("_blank");
  });

  it("states the Act carries a repeal record without claiming the section is void", () => {
    renderMessage({ citations: [REPEALED_CITATION], currency_labels: [REPEALED_LABEL] });

    const badge = screen.getByRole("link", { name: /warning:/i });
    expect(badge.getAttribute("title")).toBe(
      "Act 762 carries a repeal record dated 06/01/2018. This does not mean Section 9 itself is void — open the repeal record to check.",
    );
  });
});

describe("supersede badge", () => {
  it("renders no badge for a current_as_indexed label", () => {
    renderMessage({ citations: [CURRENT_CITATION], currency_labels: [CURRENT_AS_INDEXED_LABEL] });
    expect(screen.queryByText(/act amended/i)).toBeNull();
  });

  it("shows the badge only on the citation for the superseded Act", () => {
    renderMessage({
      citations: [SUPERSEDED_CITATION, CURRENT_CITATION],
      currency_labels: [SUPERSEDED_LABEL, UNKNOWN_LABEL],
    });

    expect(screen.getAllByText(/act amended/i)).toHaveLength(1);
  });

  it("shows the Act number and amendment date in the visible badge text", () => {
    renderMessage({ citations: [SUPERSEDED_CITATION], currency_labels: [SUPERSEDED_LABEL] });
    expect(screen.getByText("Act amended 26/04/2026")).toBeTruthy();
  });

  it("links to the amendment record, not the Act's own PDF", () => {
    renderMessage({ citations: [SUPERSEDED_CITATION], currency_labels: [SUPERSEDED_LABEL] });

    const badge = screen.getByRole("link", { name: /notice:/i });
    expect(badge.getAttribute("href")).toBe(SUPERSEDED_LABEL.detail_url);
    expect(badge.getAttribute("target")).toBe("_blank");
  });

  it("states the Act was amended without claiming the section itself changed", () => {
    renderMessage({ citations: [SUPERSEDED_CITATION], currency_labels: [SUPERSEDED_LABEL] });

    const badge = screen.getByRole("link", { name: /notice:/i });
    expect(badge.getAttribute("title")).toBe(
      "Act 155 has been amended since the reprint we indexed (26/04/2026). This does not mean Section 6 itself changed — open the amendment to check.",
    );
  });

  it("does not show the repealed-style badge for a superseded label", () => {
    renderMessage({ citations: [SUPERSEDED_CITATION], currency_labels: [SUPERSEDED_LABEL] });
    expect(screen.queryByText(/act repealed/i)).toBeNull();
  });
});
