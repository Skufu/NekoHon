export function CatIcon({ size, className }: { size: number; className: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d="M2 18c3-1.5 6-1.5 10 0 4-1.5 7-1.5 10 0v-11c-3-1.5-6-1.5-10 0-4-1.5-7-1.5-10 0v11z" />
      <path d="M12 7v11" />
      <path d="M7 6c0-2 2-3.5 4-3.5s3.5 1 4 2.5" />
      <path d="M9 2.5L9.5 4" />
      <path d="M13.5 2.5L13 4" />
      <path d="M15 5c1.5 0 2.5.8 2.5 2" />
    </svg>
  );
}

export function CloseIcon({ size, round }: { size: number; round?: boolean }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap={round ? "round" : undefined}
      strokeLinejoin={round ? "round" : undefined}
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}
