import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_RECEIPT_PANE_WIDTH,
  MAX_RECEIPT_PANE_WIDTH,
  MIN_RECEIPT_PANE_WIDTH,
  ReceiptPaneResizer,
  clampReceiptPaneWidth,
  defaultReceiptPaneWidth,
} from "./ReceiptPaneResizer";

describe("receipt pane sizing", () => {
  it("derives a balanced default and clamps both panes to useful widths", () => {
    expect(defaultReceiptPaneWidth(1280)).toBe(549);
    expect(clampReceiptPaneWidth(200, 1280)).toBe(MIN_RECEIPT_PANE_WIDTH);
    expect(clampReceiptPaneWidth(900, 1280)).toBe(596);
    expect(clampReceiptPaneWidth(900, 1920)).toBe(MAX_RECEIPT_PANE_WIDTH);
    expect(DEFAULT_RECEIPT_PANE_WIDTH).toBeGreaterThan(MIN_RECEIPT_PANE_WIDTH);
  });

  it("gives the receipt pane the sidebar's width back when the sidebar is 0", () => {
    expect(clampReceiptPaneWidth(900, 1100)).toBe(440);
    expect(clampReceiptPaneWidth(900, 1100, 0)).toBe(672);
    expect(clampReceiptPaneWidth(900, 1300, 0)).toBe(MAX_RECEIPT_PANE_WIDTH);
    expect(defaultReceiptPaneWidth(1100)).toBe(440);
    expect(defaultReceiptPaneWidth(1100, 0)).toBe(590);
  });

  it("uses the sidebarWidth prop for its limits and reset", async () => {
    render(<ReceiptPaneResizer
      width={550}
      viewportWidth={1100}
      sidebarWidth={0}
      onResize={() => {}}
      onDraggingChange={() => {}}
    />);
    const separator = screen.getByRole("separator", { name: "Resize Citation Receipt" });
    expect(separator).toHaveAttribute("aria-valuemax", "672");
  });

  it("supports keyboard resizing, limits, and reset", async () => {
    function Harness() {
      const [width, setWidth] = useState(550);
      return <ReceiptPaneResizer
        width={width}
        viewportWidth={1280}
        onResize={(nextWidth) => setWidth(nextWidth)}
        onDraggingChange={() => {}}
      />;
    }

    render(<Harness />);
    const separator = screen.getByRole("separator", { name: "Resize Citation Receipt" });
    expect(separator).toHaveClass("hidden");

    separator.focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(separator).toHaveAttribute("aria-valuenow", "582");
    await userEvent.keyboard("{End}");
    expect(separator).toHaveAttribute("aria-valuenow", "596");
    await userEvent.keyboard("{Home}");
    expect(separator).toHaveAttribute("aria-valuenow", String(MIN_RECEIPT_PANE_WIDTH));
    fireEvent.doubleClick(separator);
    expect(separator).toHaveAttribute("aria-valuenow", "549");
  });

  it("tracks pointer movement and commits the final width", () => {
    function Harness() {
      const [width, setWidth] = useState(550);
      const [committed, setCommitted] = useState(false);
      return <>
        <ReceiptPaneResizer
          width={width}
          viewportWidth={1280}
          onResize={(nextWidth, commit) => {
            setWidth(nextWidth);
            if (commit) setCommitted(true);
          }}
          onDraggingChange={() => {}}
        />
        <output>{committed ? "committed" : "resizing"}</output>
      </>;
    }

    render(<Harness />);
    const separator = screen.getByRole("separator", { name: "Resize Citation Receipt" });
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 730 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 700 });

    expect(separator).toHaveAttribute("aria-valuenow", "580");
    expect(screen.getByText("resizing")).toBeInTheDocument();

    fireEvent.pointerUp(separator, { pointerId: 1, clientX: 700 });
    expect(screen.getByText("committed")).toBeInTheDocument();
  });
});
