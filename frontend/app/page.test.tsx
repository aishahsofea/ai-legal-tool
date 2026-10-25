import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EXAMPLE_MESSAGES, EXAMPLE_META } from "@/lib/fixtures/exampleAnswer";
import Landing from "./page";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("react-pdf", () => ({
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
  Document: () => null,
  Page: () => null,
}));

describe("Landing saved example", () => {
  it("labels the example with the date it was produced", () => {
    render(<Landing />);
    expect(screen.getByText(`Saved example · produced ${EXAMPLE_META.producedOn}`)).toBeInTheDocument();
  });

  it("renders the real fixture's citations", () => {
    render(<Landing />);
    const citations = EXAMPLE_MESSAGES.find((message) => message.role === "assistant")?.citations ?? [];
    expect(citations.length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /Open Citation Receipt/ }).length).toBeGreaterThan(0);
    for (const citation of citations) {
      expect(screen.getAllByText(citation.act_title.replace(/^\*/, ""), { exact: false }).length).toBeGreaterThan(0);
    }
  });

  it("sends a suggested chip to the workspace with its query", () => {
    render(<Landing />);
    fireEvent.click(screen.getByRole("button", { name: "EA 1955 on gig workers" }));
    expect(push).toHaveBeenCalledWith(
      `/workspace?q=${encodeURIComponent("Does the Employment Act 1955 apply to gig workers after the 2022 amendments?")}`,
    );
  });

  it("makes no /query request on mount", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<Landing />);
    expect(fetchSpy.mock.calls.filter(([url]) => String(url).includes("/query"))).toEqual([]);
  });
});
