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
      className={`inline-flex cursor-pointer items-center justify-center rounded-sm bg-(--bronze) px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-background transition-colors duration-150 hover:bg-foreground active:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-(--bronze) ${className}`}
    >
      {leading ? <span className="text-xs font-light">{leading}</span> : null}
      {children}
    </button>
  );
}
