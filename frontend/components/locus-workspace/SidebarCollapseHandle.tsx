"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export const SIDEBAR_COLLAPSE_DRAG_THRESHOLD = 64;

type Preview = "collapse" | "expand";

export function SidebarCollapseHandle({
  collapsed,
  onCollapsedChange,
  onDraggingChange,
}: {
  collapsed: boolean;
  onCollapsedChange: (next: boolean) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const activePointer = useRef<number | null>(null);
  const startX = useRef(0);
  const previewRef = useRef<Preview | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);

  const updatePreview = (next: Preview | null) => {
    previewRef.current = next;
    setPreview(next);
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    activePointer.current = event.pointerId;
    startX.current = event.clientX;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onDraggingChange(true);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    const dx = event.clientX - startX.current;
    if (!collapsed && dx <= -SIDEBAR_COLLAPSE_DRAG_THRESHOLD) updatePreview("collapse");
    else if (collapsed && dx >= SIDEBAR_COLLAPSE_DRAG_THRESHOLD) updatePreview("expand");
    else updatePreview(null);
  };

  const finishPointerDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    activePointer.current = null;
    onDraggingChange(false);
    const committed = previewRef.current !== null;
    updatePreview(null);
    if (committed) onCollapsedChange(!collapsed);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter") onCollapsedChange(!collapsed);
    else if (event.key === "ArrowLeft" && !collapsed) onCollapsedChange(true);
    else if (event.key === "ArrowRight" && collapsed) onCollapsedChange(false);
    else return;
    event.preventDefault();
  };

  return (
    <div
      className="workspace-sidebar-handle"
      data-preview={preview ?? undefined}
      role="separator"
      aria-label="Thread list"
      aria-controls="workspace-thread-sidebar"
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={collapsed ? 0 : 100}
      tabIndex={0}
      title={collapsed ? "Drag right to show thread list" : "Drag left to hide thread list"}
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
