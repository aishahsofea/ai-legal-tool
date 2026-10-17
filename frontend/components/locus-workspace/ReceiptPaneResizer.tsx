"use client";

import { useRef, type KeyboardEvent, type PointerEvent } from "react";

export const WORKSPACE_SIDEBAR_WIDTH = 256;
export const RECEIPT_RESIZER_WIDTH = 8;
export const MIN_CHAT_PANE_WIDTH = 420;
export const MIN_RECEIPT_PANE_WIDTH = 440;
export const MAX_RECEIPT_PANE_WIDTH = 800;
export const DEFAULT_RECEIPT_PANE_WIDTH = 640;

const KEYBOARD_RESIZE_STEP = 32;
const DEFAULT_RECEIPT_RATIO = 0.54;

export function maxReceiptPaneWidth(viewportWidth: number, sidebarWidth = WORKSPACE_SIDEBAR_WIDTH) {
  const available = viewportWidth - sidebarWidth - RECEIPT_RESIZER_WIDTH - MIN_CHAT_PANE_WIDTH;
  return Math.max(MIN_RECEIPT_PANE_WIDTH, Math.min(MAX_RECEIPT_PANE_WIDTH, available));
}

export function clampReceiptPaneWidth(width: number, viewportWidth: number, sidebarWidth = WORKSPACE_SIDEBAR_WIDTH) {
  return Math.round(Math.min(maxReceiptPaneWidth(viewportWidth, sidebarWidth), Math.max(MIN_RECEIPT_PANE_WIDTH, width)));
}

export function defaultReceiptPaneWidth(viewportWidth: number, sidebarWidth = WORKSPACE_SIDEBAR_WIDTH) {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return DEFAULT_RECEIPT_PANE_WIDTH;
  const workspaceWidth = viewportWidth - sidebarWidth - RECEIPT_RESIZER_WIDTH;
  return clampReceiptPaneWidth(workspaceWidth * DEFAULT_RECEIPT_RATIO, viewportWidth, sidebarWidth);
}

export function ReceiptPaneResizer({
  width,
  viewportWidth,
  sidebarWidth = WORKSPACE_SIDEBAR_WIDTH,
  onResize,
  onDraggingChange,
}: {
  width: number;
  viewportWidth: number;
  sidebarWidth?: number;
  onResize: (width: number, commit: boolean) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const activePointer = useRef<number | null>(null);
  const lastWidth = useRef(width);
  const maximum = maxReceiptPaneWidth(viewportWidth, sidebarWidth);

  const resizeTo = (nextWidth: number, commit: boolean) => {
    const clamped = clampReceiptPaneWidth(nextWidth, viewportWidth, sidebarWidth);
    lastWidth.current = clamped;
    onResize(clamped, commit);
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    activePointer.current = event.pointerId;
    lastWidth.current = width;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onDraggingChange(true);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    resizeTo(viewportWidth - event.clientX, false);
  };

  const finishPointerResize = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    activePointer.current = null;
    onDraggingChange(false);
    onResize(lastWidth.current, true);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    let nextWidth: number | null = null;
    if (event.key === "ArrowLeft") nextWidth = width + KEYBOARD_RESIZE_STEP;
    if (event.key === "ArrowRight") nextWidth = width - KEYBOARD_RESIZE_STEP;
    if (event.key === "Home") nextWidth = MIN_RECEIPT_PANE_WIDTH;
    if (event.key === "End") nextWidth = maximum;
    if (nextWidth === null) return;
    event.preventDefault();
    resizeTo(nextWidth, true);
  };

  return (
    <div
      className="workspace-receipt-resizer hidden"
      role="separator"
      aria-label="Resize Citation Receipt"
      aria-controls="citation-receipt-pane"
      aria-orientation="vertical"
      aria-valuemin={MIN_RECEIPT_PANE_WIDTH}
      aria-valuemax={maximum}
      aria-valuenow={width}
      tabIndex={0}
      title="Drag to resize · double-click to reset"
      onDoubleClick={() => resizeTo(defaultReceiptPaneWidth(viewportWidth, sidebarWidth), true)}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointerResize}
      onPointerCancel={finishPointerResize}
    >
      <span aria-hidden="true" />
    </div>
  );
}
