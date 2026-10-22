import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SIDEBAR_COLLAPSE_DRAG_THRESHOLD, SidebarCollapseHandle } from "./SidebarCollapseHandle";

function setup(collapsed: boolean) {
  const onCollapsedChange = vi.fn();
  const onDraggingChange = vi.fn();
  render(<SidebarCollapseHandle
    collapsed={collapsed}
    onCollapsedChange={onCollapsedChange}
    onDraggingChange={onDraggingChange}
  />);
  const separator = screen.getByRole("separator", { name: "Thread list" });
  return { separator, onCollapsedChange, onDraggingChange };
}

function drag(separator: HTMLElement, dx: number, end: "pointerUp" | "pointerCancel" = "pointerUp") {
  fireEvent.pointerDown(separator, { pointerId: 1, clientX: 300 });
  fireEvent.pointerMove(separator, { pointerId: 1, clientX: 300 + dx });
  fireEvent[end](separator, { pointerId: 1, clientX: 300 + dx });
}

describe("SidebarCollapseHandle", () => {
  it("uses a 64px threshold", () => {
    expect(SIDEBAR_COLLAPSE_DRAG_THRESHOLD).toBe(64);
  });

  it("collapses an expanded sidebar when dragged left by the threshold", () => {
    const { separator, onCollapsedChange } = setup(false);
    drag(separator, -64);
    expect(onCollapsedChange).toHaveBeenCalledTimes(1);
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("does nothing for a shorter drag left", () => {
    const { separator, onCollapsedChange } = setup(false);
    drag(separator, -63);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("expands a collapsed sidebar when dragged right by the threshold", () => {
    const { separator, onCollapsedChange } = setup(true);
    drag(separator, 64);
    expect(onCollapsedChange).toHaveBeenCalledTimes(1);
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
  });

  it("does nothing for a shorter drag right or a drag left when collapsed", () => {
    const { separator, onCollapsedChange } = setup(true);
    drag(separator, 63);
    drag(separator, -100);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("does nothing for an expanded drag right", () => {
    const { separator, onCollapsedChange } = setup(false);
    drag(separator, 100);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  it("commits only on release and shows a preview meanwhile", () => {
    const { separator, onCollapsedChange } = setup(false);
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 300 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 200 });
    expect(onCollapsedChange).not.toHaveBeenCalled();
    expect(separator).toHaveAttribute("data-preview", "collapse");
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 290 });
    expect(separator).not.toHaveAttribute("data-preview");
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 200 });
    fireEvent.pointerUp(separator, { pointerId: 1, clientX: 200 });
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
    expect(separator).not.toHaveAttribute("data-preview");
  });

  it("commits on pointercancel past the threshold", () => {
    const { separator, onCollapsedChange } = setup(false);
    drag(separator, -80, "pointerCancel");
    expect(onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("reports dragging true then false", () => {
    const { separator, onDraggingChange } = setup(false);
    drag(separator, -10);
    expect(onDraggingChange.mock.calls).toEqual([[true], [false]]);
  });

  it("ignores moves and releases from another pointer", () => {
    const { separator, onCollapsedChange, onDraggingChange } = setup(false);
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 300 });
    fireEvent.pointerMove(separator, { pointerId: 2, clientX: 100 });
    fireEvent.pointerUp(separator, { pointerId: 2, clientX: 100 });
    expect(separator).not.toHaveAttribute("data-preview");
    expect(onCollapsedChange).not.toHaveBeenCalled();
    expect(onDraggingChange).toHaveBeenCalledTimes(1);
  });

  it("toggles on Enter", async () => {
    const expanded = setup(false);
    expanded.separator.focus();
    await userEvent.keyboard("{Enter}");
    expect(expanded.onCollapsedChange).toHaveBeenCalledWith(true);
  });

  it("toggles on Enter when collapsed", async () => {
    const { separator, onCollapsedChange } = setup(true);
    separator.focus();
    await userEvent.keyboard("{Enter}");
    expect(onCollapsedChange).toHaveBeenCalledWith(false);
  });

  it("collapses on ArrowLeft only when expanded", async () => {
    const expanded = setup(false);
    expanded.separator.focus();
    await userEvent.keyboard("{ArrowLeft}{ArrowRight}");
    expect(expanded.onCollapsedChange.mock.calls).toEqual([[true]]);
  });

  it("expands on ArrowRight only when collapsed", async () => {
    const { separator, onCollapsedChange } = setup(true);
    separator.focus();
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}");
    expect(onCollapsedChange.mock.calls).toEqual([[false]]);
  });

  it("exposes separator ARIA state", () => {
    const expanded = setup(false);
    expect(expanded.separator).toHaveAttribute("aria-controls", "workspace-thread-sidebar");
    expect(expanded.separator).toHaveAttribute("aria-orientation", "vertical");
    expect(expanded.separator).toHaveAttribute("aria-valuemin", "0");
    expect(expanded.separator).toHaveAttribute("aria-valuemax", "100");
    expect(expanded.separator).toHaveAttribute("aria-valuenow", "100");
    expect(expanded.separator).toHaveAttribute("tabindex", "0");
    expect(expanded.separator).toHaveAttribute("title", "Drag left to hide thread list");
  });

  it("reports 0 and a reopen tooltip when collapsed", () => {
    const { separator } = setup(true);
    expect(separator).toHaveAttribute("aria-valuenow", "0");
    expect(separator).toHaveAttribute("title", "Drag right to show thread list");
  });
});
