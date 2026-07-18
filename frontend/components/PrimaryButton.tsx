import { type ButtonHTMLAttributes, type ReactNode } from "react";

export function PrimaryButton({
  className = "",
  children,
  leading,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { leading?: ReactNode }) {
  return (
    <button
      {...props}
      className={`inline-flex min-h-10 cursor-pointer items-center justify-center rounded-xl bg-(--accent) px-4 py-2 text-xs font-semibold tracking-[0.02em] text-(--surface) shadow-[var(--shadow-soft)] transition-colors duration-200 hover:bg-(--accent-deep) active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-(--accent) ${className}`}
    >
      {leading ? <span className="text-base font-light">{leading}</span> : null}
      {children}
    </button>
  );
}
