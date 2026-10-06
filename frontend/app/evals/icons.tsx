type IconProps = { className?: string };
type SpinnerProps = IconProps & { size?: number };

export function ChevronDown({ className }: IconProps) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

export function Play({ className }: IconProps) {
  return (
    <svg className={className} width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
      <path d="M3 1.5v9a.5.5 0 0 0 .76.43l7.2-4.5a.5.5 0 0 0 0-.86l-7.2-4.5A.5.5 0 0 0 3 1.5z" />
    </svg>
  );
}

export function Stop({ className }: IconProps) {
  return (
    <svg className={className} width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
      <rect x="2" y="2" width="8" height="8" rx="1.5" />
    </svg>
  );
}

// Reduced-motion users get a static arc instead of a spinning one.
export function Spinner({ className, size = 14 }: SpinnerProps) {
  return (
    <svg className={`motion-safe:animate-spin ${className ?? ""}`} width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="8" cy="8" r="6" opacity="0.25" />
      <path d="M14 8a6 6 0 0 0-6-6" />
    </svg>
  );
}
