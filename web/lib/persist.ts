import type { BookCatalogItem } from "./engine";
import type { MarkerColor, UserHighlight } from "./anchor";
import type { GlossItem, Status } from "./turns";

export type ThemeName = "night" | "paper" | "sepia" | "snow" | "ink";
export type PenName = "vermilion" | "cobalt" | "moss" | "graphite";

export type Settings = { theme: ThemeName; pen: PenName; marker: MarkerColor; readSize: number };
export type BookProgress = { pct: number; chapter: string; chunkId: string; lastReadAt: number };
export type ProgressMap = Record<string, BookProgress>;

export function saveSettings(settings: Settings) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("atb-settings", JSON.stringify(settings));
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.pen = settings.pen;
    document.documentElement.style.setProperty("--read-size", `${settings.readSize}px`);
  } catch {}
}

export function loadSettings(): Settings {
  const settings: Settings = { theme: "night", pen: "vermilion", marker: "yellow", readSize: 19 };
  try {
    const rawSettings = localStorage.getItem("atb-settings");
    if (rawSettings) {
      const parsed = JSON.parse(rawSettings);
      if (parsed.theme) settings.theme = parsed.theme;
      if (parsed.pen) settings.pen = parsed.pen;
      if (parsed.marker) settings.marker = parsed.marker;
      if (typeof parsed.readSize === "number") {
        settings.readSize = Math.max(15, Math.min(26, parsed.readSize));
      }
    }
  } catch {}
  return settings;
}

export function saveHighlights(highlights: UserHighlight[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("atb-highlights", JSON.stringify(highlights));
  } catch {}
}

export function saveBookState(bookId: string, highlights: UserHighlight[], glosses: GlossItem[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(`nekohon-state-${bookId}`, JSON.stringify({ highlights, glosses }));
  } catch {}
}

export function loadBookState(bookId: string): { highlights: UserHighlight[]; glosses: GlossItem[] } {
  if (typeof window === "undefined") return { highlights: [], glosses: [] };
  try {
    const raw = localStorage.getItem(`nekohon-state-${bookId}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        highlights: Array.isArray(parsed.highlights) ? parsed.highlights : [],
        glosses: Array.isArray(parsed.glosses)
          ? parsed.glosses.map((g: GlossItem) => ({
              ...g,
              turns: (g.turns || []).map((t) =>
                t.status === "loading" || t.status === "streaming"
                  ? { ...t, status: "stopped" as Status, streamText: "" }
                  : t
              ),
            }))
          : [],
      };
    }
    if (bookId === "fde") {
      const legacyHl = localStorage.getItem("atb-highlights");
      if (legacyHl) {
        const parsed = JSON.parse(legacyHl);
        if (Array.isArray(parsed)) {
          saveBookState("fde", parsed, []);
          return { highlights: parsed, glosses: [] };
        }
      }
    }
  } catch {}
  return { highlights: [], glosses: [] };
}

let saveProgressTimer: ReturnType<typeof setTimeout> | null = null;
let pendingProgress: ProgressMap | null = null;

function flushProgress(): void {
  if (typeof window === "undefined" || !pendingProgress) return;
  if (saveProgressTimer) {
    clearTimeout(saveProgressTimer);
    saveProgressTimer = null;
  }
  try {
    localStorage.setItem("nekohon-progress", JSON.stringify(pendingProgress));
  } catch {}
  pendingProgress = null;
}

export function saveProgress(progress: ProgressMap) {
  if (typeof window === "undefined") return;
  pendingProgress = progress;
  if (saveProgressTimer) clearTimeout(saveProgressTimer);
  saveProgressTimer = setTimeout(() => {
    flushProgress();
  }, 1000);
}

if (typeof window !== "undefined") {
  const onFlush = () => {
    flushProgress();
  };
  const onVisibilityChange = () => {
    if (document.visibilityState === "hidden") {
      flushProgress();
    }
  };
  window.addEventListener("pagehide", onFlush);
  window.addEventListener("beforeunload", onFlush);
  document.addEventListener("visibilitychange", onVisibilityChange);
}

export function loadProgress(): ProgressMap {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem("nekohon-progress");
    if (raw) return JSON.parse(raw);
  } catch {}
  return {};
}

export function saveCatalog(catalog: BookCatalogItem[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("nekohon-catalog", JSON.stringify(catalog));
  } catch {}
}

export function loadCatalog(): BookCatalogItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem("nekohon-catalog");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch {}
  return [];
}
