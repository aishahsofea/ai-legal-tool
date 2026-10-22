import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  SIDEBAR_COLLAPSE_THRESHOLD,
  SidebarResizeHandle,
  clampSidebarWidth,
} from "./SidebarResizeHandle";

function setup(collapsed: boolean, width = 256) {
  const onResize = vi.fn();
  const onCollapsedChange = vi.fn();
  const onDraggingChange = vi.fn();
  render(<SidebarResizeHandle
    width={width}
    collapsed={collapsed}
    onResize={onResize}
    onCollapsedChange={onCollapsedChange}
    onDraggingChange={onDraggingChange}
  />);
  const separator = screen.getByRole("separator", { name: "Resize thread list" });
  return { separator, onResize, onCollapsedChange, onDraggingChange };
}

function drag(separator: HTMLElement, startX: number, ...moves: number[]) {
  fireEvent.pointerDown(separator, { pointerId: 1, clientX: startX });
  for (const x of moves) fireEvent.pointerMove(separator, { pointerId: 1, clientX: x });
  fireEvent.pointerUp(separator, { pointerId: 1, clientX: moves.at(-1) ?? startX });
}

describe("clampSidebarWidth", () => {
  it("keeps the width between the bounds", () => {
    expect(clampSidebarWidth(MIN_SIDEBAR_WIDTH - 10)).toBe(MIN_SIDEBAR_WIDTH);
    expect(clampSidebarWidth(230.4)).toBe(230);
    expect(clampSidebarWidth(9999)).toBe(MAX_SIDEBAR_WIDTH);
  });
});

describe("SidebarResizeHandle", () => {
  it("collapses a drag before it reaches the min width", () => {
    expect(SIDEBAR_COLLAPSE_THRESHOLD).toBeGreaterThan(MIN_SIDEBAR_WIDTH);
  });

  it("never widens past the default width", () => {
    expect(MAX_SIDEBAR_WIDTH).toBe(256);
  });

  it("resizes live while dragging and commits the last width on release", () => {
    const { separator, onResize } = setup(false);
    drag(separator, 260, 240, 220);
    expect(onResize.mock.calls).toEqual([[236, false], [216, false], [216, true]]);
  });

  it("clamps the dragged width to the max", () => {
    const { separator, onResize } = setup(false);
    drag(separator, 256, 900);
    expect(onResize.mock.calls).toEqual([[MAX_SIDEBAR_WIDTH, false], [MAX_SIDEBAR_WIDTH, true]]);
  });

  it("collapses once the edge crosses the threshold and keeps the last expanded width", () => {
    const { separator, onResize, onCollapsedChange } = setup(false);
    drag(separator, 256, 220, SIDEBAR_COLLAPSE_THRESHOLD - 1, 10);
    expect(onCollapsedChange.mock.calls).toEqual([[true]]);
    expect(onResize.mock.calls.at(-1)).toEqual([220, true]);
  });

  it("does not collapse at exactly the threshold", () => {
    const { separator, onCollapsedChange } = setup(false);
    drag(separator, 256, SIDEBAR_COLLAPSE_THRESHOLD);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("reopens mid-drag when dragged back past the threshold", () => {
    const { separator, onCollapsedChange, onResize } = setup(false);
    drag(separator, 256, 50, 230);
    expect(onCollapsedChange.mock.calls).toEqual([[true], [false]]);
    expect(onResize.mock.calls.at(-1)).toEqual([230, true]);
  });

  it("expands a collapsed sidebar when dragged right past the threshold", () => {
    const { separator, onCollapsedChange, onResize } = setup(true);
    drag(separator, 4, 4 + SIDEBAR_COLLAPSE_THRESHOLD - 1);
    expect(onCollapsedChange).not.toHaveBeenCalled();
    drag(separator, 4, 4 + 230);
    expect(onCollapsedChange.mock.calls).toEqual([[false]]);
    expect(onResize.mock.calls.at(-1)).toEqual([230, true]);
  });

  it("reports dragging true then false", () => {
    const { separator, onDraggingChange } = setup(false);
    drag(separator, 256, 240);
    expect(onDraggingChange.mock.calls).toEqual([[true], [false]]);
  });

  it("commits on pointercancel", () => {
    const { separator, onResize } = setup(false);
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 256 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 230 });
    fireEvent.pointerCancel(separator, { pointerId: 1, clientX: 230 });
    expect(onResize.mock.calls.at(-1)).toEqual([230, true]);
  });

  it("ignores moves and releases from another pointer", () => {
    const { separator, onResize, onCollapsedChange, onDraggingChange } = setup(false);
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 256 });
    fireEvent.pointerMove(separator, { pointerId: 2, clientX: 10 });
    fireEvent.pointerUp(separator, { pointerId: 2, clientX: 10 });
    expect(onResize).not.toHaveBeenCalled();
    expect(onCollapsedChange).not.toHaveBeenCalled();
    expect(onDraggingChange).toHaveBeenCalledTimes(1);
  });

  it("toggles on Enter", async () => {
    const expanded = setup(false);
    expanded.separator.focus();
    await userEvent.keyboard("{Enter}");
    expect(expanded.onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("resizes with arrow keys when expanded", async () => {
    const { separator, onResize, onCollapsedChange } = setup(false, 230);
    separator.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}");
    expect(onResize.mock.calls).toEqual([[246, true], [214, true]]);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("collapses on ArrowLeft at the min width", async () => {
    const { separator, onResize, onCollapsedChange } = setup(false, MIN_SIDEBAR_WIDTH);
    separator.focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onCollapsedChange.mock.calls).toEqual([[true]]);
    expect(onResize).not.toHaveBeenCalled();
  });

  it("expands on ArrowRight only when collapsed", async () => {
    const { separator, onCollapsedChange, onResize } = setup(true);
    separator.focus();
    await userEvent.keyboard("{ArrowLeft}{ArrowRight}");
    expect(onCollapsedChange.mock.calls).toEqual([[false]]);
    expect(onResize).not.toHaveBeenCalled();
  });

  it("resets to the default width on double-click, reopening if collapsed", () => {
    const { separator, onResize, onCollapsedChange } = setup(true, 210);
    fireEvent.doubleClick(separator);
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
    expect(onResize).toHaveBeenCalledWith(256, true);
  });

  it("exposes separator ARIA state", () => {
    const expanded = setup(false, 230);
    expect(expanded.separator).toHaveAttribute("aria-controls", "workspace-thread-sidebar");
    expect(expanded.separator).toHaveAttribute("aria-orientation", "vertical");
    expect(expanded.separator).toHaveAttribute("aria-valuemin", "0");
    expect(expanded.separator).toHaveAttribute("aria-valuemax", String(MAX_SIDEBAR_WIDTH));
    expect(expanded.separator).toHaveAttribute("aria-valuenow", "230");
    expect(expanded.separator).toHaveAttribute("tabindex", "0");
  });

  it("reports 0 and a reopen tooltip when collapsed", () => {
    const { separator } = setup(true);
    expect(separator).toHaveAttribute("aria-valuenow", "0");
    expect(separator).toHaveAttribute("title", "Drag right to show thread list");
  });
});
