type IconProps = { className?: string };
type SpinnerProps = IconProps & { size?: number };

export function ChevronDown({ className }: IconProps) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

export function Copy({ className }: IconProps) {
  return (
    <svg data-icon="copy" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
    </svg>
  );
}

export function Check({ className }: IconProps) {
  return (
    <svg data-icon="check" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 8.5l3.5 3.5L13 4.5" />
    </svg>
  );
}

export function Trash({ className }: IconProps) {
  return (
    <svg data-icon="trash" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.5 4h11M6 4V2.5h4V4M4 4l.6 9a1 1 0 0 0 1 .9h4.8a1 1 0 0 0 1-.9L12 4M6.75 6.75v4M9.25 6.75v4" />
    </svg>
  );
}

export function Share({ className }: IconProps) {
  return (
    <svg data-icon="share" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="3.5" r="2" />
      <circle cx="4" cy="8" r="2" />
      <circle cx="12" cy="12.5" r="2" />
      <path d="M5.75 7l4.5-2.5M5.75 9l4.5 2.5" />
    </svg>
  );
}

export function PanelLeft({ className }: IconProps) {
  return (
    <svg data-icon="panel-left" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M6 3v10" />
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

export function SignOut({ className }: IconProps) {
  return (
    <svg data-icon="sign-out" className={className} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6.5 2.5h-3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3M10 5l3 3-3 3M13 8H6" />
    </svg>
  );
}
