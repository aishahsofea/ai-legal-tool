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
      className={`rounded-sm bg-(--bronze) px-3 py-3 text-xs font-semibold uppercase tracking-wide text-background transition-colors duration-150 hover:bg-foreground ${className}`}
    >
      {leading ? <span className="text-sm font-light">{leading}</span> : null}
      {children}
    </button>
  );
}
