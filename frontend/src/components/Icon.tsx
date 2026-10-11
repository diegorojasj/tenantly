// A tiny inline icon set: one <path> per glyph, stroked with currentColor so
// icons inherit the tenant tint. No icon font, no sprite request.
const paths = {
  overview: 'M4 13h6V4H4zM14 20h6v-9h-6zM4 20h6v-3H4zM14 7h6V4h-6z',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4M8 14h3M8 17h6',
  pipeline: 'M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v6h-4z',
  users: 'M9 11a4 4 0 100-8 4 4 0 000 8zM2 21v-1a6 6 0 0112 0v1M16 3.5a4 4 0 010 7M22 21v-1a6 6 0 00-4-5.6',
  tag: 'M3 12V4h8l10 10-8 8zM7.5 8.5h.01',
  plus: 'M12 5v14M5 12h14',
  arrowLeft: 'M15 6l-6 6 6 6',
  clock: 'M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
  structure: 'M12 3v5M12 8H6v4M12 8h6v4M4 12h4v4H4zM16 12h4v4h-4zM10 16h4v5h-4zM6 16v2h4M18 16v2h-4',
  access: 'M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6zM9 12l2 2 4-4',
  config: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 4v6M8 14v6',
  audit: 'M6 3h9l4 4v14H6zM15 3v4h4M9 12h7M9 16h5',
  integrations: 'M9 7V4M15 7V4M7 7h10v4a5 5 0 01-10 0zM12 16v5',
  billing: 'M3 7h18v12H3zM3 11h18M7 15h4',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zM21 21l-4.5-4.5',
  chevron: 'M9 6l6 6-6 6',
  lock: 'M6 11h12v9H6zM9 11V8a3 3 0 016 0v3',
  check: 'M5 12l5 5 9-10',
  x: 'M6 6l12 12M18 6L6 18',
  link: 'M10 14a4 4 0 006 0l3-3a4 4 0 00-6-6l-1 1M14 10a4 4 0 00-6 0l-3 3a4 4 0 006 6l1-1',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  swap: 'M7 4L3 8l4 4M3 8h14M17 12l4 4-4 4M21 16H7',
  dot: 'M12 11a1 1 0 100 2 1 1 0 000-2z',
  shield: 'M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z',
  reset: 'M4 12a8 8 0 108-8H8M8 1L5 4l3 3',
} as const;

export type IconName = keyof typeof paths;

export default function Icon(props: { name: IconName; size?: number; label?: string }) {
  return (
    <svg
      class="icon"
      width={props.size ?? 18}
      height={props.size ?? 18}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      role={props.label ? 'img' : undefined}
      aria-label={props.label}
      aria-hidden={props.label ? undefined : 'true'}
    >
      <path d={paths[props.name]} />
    </svg>
  );
}
