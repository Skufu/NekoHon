export type Marker = "yellow" | "green" | "blue" | "pink";

export const THEMES = [
  { key: "night", label: "Night", bg: "var(--swatch-night-bg)", fg: "var(--swatch-night-fg)", dark: true },
  { key: "paper", label: "Paper", bg: "var(--swatch-paper-bg)", fg: "var(--swatch-paper-fg)", dark: false },
  { key: "sepia", label: "Sepia", bg: "var(--swatch-sepia-bg)", fg: "var(--swatch-sepia-fg)", dark: false },
  { key: "snow", label: "Snow", bg: "var(--swatch-snow-bg)", fg: "var(--swatch-snow-fg)", dark: false },
  { key: "ink", label: "Ink", bg: "var(--swatch-ink-bg)", fg: "var(--swatch-ink-fg)", dark: true },
] as const;

export const PENS = [
  { key: "vermilion", label: "Vermilion", color: "var(--swatch-vermilion)" },
  { key: "cobalt", label: "Cobalt", color: "var(--swatch-cobalt)" },
  { key: "moss", label: "Moss", color: "var(--swatch-moss)" },
  { key: "graphite", label: "Graphite", color: "var(--swatch-graphite)" },
] as const;

export const MARKERS: { key: Marker; label: string; color: string }[] = [
  { key: "yellow", label: "Yellow", color: "var(--mk-yellow)" },
  { key: "green", label: "Green", color: "var(--mk-green)" },
  { key: "blue", label: "Blue", color: "var(--mk-blue)" },
  { key: "pink", label: "Pink", color: "var(--mk-pink)" },
];
