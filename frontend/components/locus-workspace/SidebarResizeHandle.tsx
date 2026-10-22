"use client";

import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { WORKSPACE_SIDEBAR_WIDTH } from "./ReceiptPaneResizer";

export const MIN_SIDEBAR_WIDTH = 40;
export const MAX_SIDEBAR_WIDTH = WORKSPACE_SIDEBAR_WIDTH;
// Below MIN so the width sticks at MIN briefly before the sidebar snaps shut.
export const SIDEBAR_COLLAPSE_THRESHOLD = 80;

const KEYBOARD_RESIZE_STEP = 16;

export function clampSidebarWidth(width: number) {
  return Math.round(Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width)));
}

export function SidebarResizeHandle({
  width,
  collapsed,
  onResize,
  onCollapsedChange,
  onDraggingChange,
}: {
  width: number;
  collapsed: boolean;
  onResize: (width: number, commit: boolean) => void;
  onCollapsedChange: (next: boolean) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const activePointer = useRef<number | null>(null);
  const edgeOffset = useRef(0);
  const lastWidth = useRef(width);
  // Moves can arrive before the collapsed prop re-renders, so track it locally mid-drag.
  const liveCollapsed = useRef(collapsed);

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    activePointer.current = event.pointerId;
    edgeOffset.current = event.clientX - (collapsed ? 0 : width);
    lastWidth.current = width;
    liveCollapsed.current = collapsed;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onDraggingChange(true);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    const edge = event.clientX - edgeOffset.current;
    const nextCollapsed = edge < SIDEBAR_COLLAPSE_THRESHOLD;
    if (nextCollapsed !== liveCollapsed.current) {
      liveCollapsed.current = nextCollapsed;
      onCollapsedChange(nextCollapsed);
    }
    if (nextCollapsed) return;
    lastWidth.current = clampSidebarWidth(edge);
    onResize(lastWidth.current, false);
  };

  const finishPointerDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    activePointer.current = null;
    onDraggingChange(false);
    onResize(lastWidth.current, true);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter") onCollapsedChange(!collapsed);
    else if (event.key === "ArrowRight" && collapsed) onCollapsedChange(false);
    else if (event.key === "ArrowRight") onResize(clampSidebarWidth(width + KEYBOARD_RESIZE_STEP), true);
    else if (event.key === "ArrowLeft" && !collapsed && width <= MIN_SIDEBAR_WIDTH) onCollapsedChange(true);
    else if (event.key === "ArrowLeft" && !collapsed) onResize(clampSidebarWidth(width - KEYBOARD_RESIZE_STEP), true);
    else return;
    event.preventDefault();
  };

  const resetWidth = () => {
    if (collapsed) onCollapsedChange(false);
    onResize(WORKSPACE_SIDEBAR_WIDTH, true);
  };

  return (
    <div
      className="workspace-sidebar-handle"
      role="separator"
      aria-label="Resize thread list"
      aria-controls="workspace-thread-sidebar"
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={MAX_SIDEBAR_WIDTH}
      aria-valuenow={collapsed ? 0 : width}
      tabIndex={0}
      title={collapsed ? "Drag right to show thread list" : "Drag to resize · drag far left to hide"}
      onDoubleClick={resetWidth}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointerDrag}
      onPointerCancel={finishPointerDrag}
    >
      <span aria-hidden="true" />
    </div>
  );
}
