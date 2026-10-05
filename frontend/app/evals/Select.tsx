"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown } from "./icons";
import { palette } from "./palette";

export type SelectOption = { value: string; label: string };

type SelectProps = {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  "aria-label"?: string;
  variant?: "field" | "pill";
  bold?: boolean;
};

// A native <select> popup is drawn by the OS: on macOS it overlays the trigger
// and CSS cannot move it. A listbox is the only way to open options below.
export function Select({ value, options, onChange, disabled, "aria-label": ariaLabel, variant = "field", bold = false }: SelectProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (open) document.getElementById(`${listboxId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, listboxId]);

  function openList() {
    setActive(selectedIndex);
    setOpen(true);
  }

  function choose(index: number) {
    const option = options[index];
    if (option) onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.key === "Escape") {
      if (open) event.preventDefault();
      setOpen(false);
      return;
    }
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (step) {
      event.preventDefault();
      if (!open) return openList();
      setActive((index) => Math.min(options.length - 1, Math.max(0, index + step)));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      if (!open) openList();
      setActive(event.key === "Home" ? 0 : options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) choose(active);
      else openList();
    }
  }

  const shape = variant === "pill" ? "rounded-full px-3 py-1.5 text-xs font-semibold" : `rounded-xl px-3 py-2.5 text-sm ${bold ? "font-semibold" : ""}`;

  return (
    <div ref={rootRef} className={`relative ${variant === "pill" ? "" : "w-full"}`}>
      <button
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-activedescendant={open ? `${listboxId}-${active}` : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        className={`flex w-full items-center justify-between gap-2 border pr-9 text-left disabled:opacity-60 ${shape}`}
        style={{ borderColor: palette.line, background: palette.panel }}
      >
        <span className="truncate">{selected?.label ?? ""}</span>
      </button>
      <ChevronDown className={`pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 transition-transform ${open ? "rotate-180" : ""}`} />
      {open && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute left-0 top-full z-30 mt-1 max-h-64 min-w-full overflow-auto rounded-xl border py-1 text-sm shadow-lg"
          style={{ borderColor: palette.line, background: palette.panel }}
        >
          {options.map((option, index) => (
            <li
              key={option.value}
              id={`${listboxId}-${index}`}
              role="option"
              aria-selected={option.value === value}
              onMouseEnter={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
              className={`cursor-pointer whitespace-nowrap px-3 py-2 ${option.value === value ? "font-semibold" : ""}`}
              style={{ background: index === active ? palette.accentSoft : undefined }}
            >
              {option.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
