"use client";

import { useEffect, useId, useRef, useState } from "react";
import { IconButton } from "@/components/chamber";
import { Check, Monitor, Moon, Sun } from "@/components/icons";
import { useTheme, type ThemeChoice } from "@/lib/useTheme";

const OPTIONS: { value: ThemeChoice; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle() {
  const [choice, setChoice] = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Neutral icon until mount so the markup matches the server HTML.
  const Current = OPTIONS.find((o) => o.value === choice)?.Icon ?? Sun;

  return (
    <div ref={rootRef} className="relative">
      <IconButton
        ref={buttonRef}
        type="button"
        aria-label="Theme"
        title="Theme"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        <Current />
      </IconButton>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Theme"
          className="chamber-shadow-popover absolute right-0 top-full z-40 mt-1 min-w-36 rounded-lg border border-(--line) bg-(--surface) p-1"
        >
          {OPTIONS.map(({ value, label, Icon }) => (
            <button
              key={value}
              type="button"
              role="menuitemradio"
              aria-checked={choice === value}
              onClick={() => {
                setChoice(value);
                setOpen(false);
                buttonRef.current?.focus();
              }}
              className="flex min-h-8 w-full cursor-pointer items-center gap-2 rounded-md px-2 text-left text-sm text-(--text-muted) hover:bg-(--line-soft) hover:text-(--text)"
            >
              <Icon />
              <span className="flex-1">{label}</span>
              {choice === value && <Check />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
