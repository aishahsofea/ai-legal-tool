import { type ButtonHTMLAttributes, type ReactNode } from "react";

type PrimaryButtonSize = "default" | "compact" | "icon";

const sizeClasses: Record<PrimaryButtonSize, string> = {
  default: "min-h-10 rounded-xl px-4 py-2 text-xs leading-4",
  compact: "min-h-8 rounded-lg px-3 py-1 text-xs leading-4",
  icon: "min-h-8 min-w-8 rounded-lg p-1 text-xs leading-4",
};

export function PrimaryButton({
  className = "",
  children,
  leading,
  size = "default",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { leading?: ReactNode; size?: PrimaryButtonSize }) {
  return (
    <button
      {...props}
      className={`inline-flex cursor-pointer items-center justify-center whitespace-nowrap bg-(--accent) font-semibold tracking-[0.02em] text-(--surface) shadow-[var(--shadow-soft)] transition-colors duration-200 hover:bg-(--accent-deep) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-(--accent) ${sizeClasses[size]} ${className}`}
    >
      {leading ? <span className="text-base font-light">{leading}</span> : null}
      {children}
    </button>
  );
}
