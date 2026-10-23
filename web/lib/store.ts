import { create } from "zustand";
import { checkHealth, prefetchChunks, type BookCatalogItem } from "./engine";
import type { MarkerColor, UserHighlight } from "./anchor";
import {
  loadBookState,
  loadCatalog,
  loadProgress,
  loadSettings,
  saveBookState,
  saveCatalog,
  saveHighlights,
  saveProgress,
  saveSettings,
  type PenName,
  type ProgressMap,
  type ThemeName,
} from "./persist";
import { abortFlights, runTurnStream, type StreamPayload } from "./stream";
import { mapTurns, patchGloss, type GlossItem, type GlossTurn, type ThreadTurn } from "./turns";

export type { ThemeName } from "./persist";
export type { MarkerColor, UserHighlight } from "./anchor";
export type { GlossItem } from "./turns";

export type Highlight = {
  chunkId: string;
  chapter: string;
  quote: string;
  at?: number;
  nonce?: number;
};

type GlossAnchor = {
  id: string;
  chunkId: string;
  endChunkId?: string;
  chapter: string;
  heading?: string;
  quote: string;
  at?: number;
};

function buildGlossAnchors(glosses: GlossItem[]): {
  anchors: GlossAnchor[];
  byChunk: Record<string, GlossAnchor[]>;
} {
  const anchors: GlossAnchor[] = [];
  const byChunk: Record<string, GlossAnchor[]> = {};
  for (const g of glosses) {
    const a: GlossAnchor = {
      id: g.id,
      chunkId: g.chunkId,
      endChunkId: g.endChunkId,
      chapter: g.chapter,
      heading: g.heading,
      quote: g.quote,
      at: g.at,
    };
    anchors.push(a);
    if (!byChunk[g.chunkId]) byChunk[g.chunkId] = [];
    byChunk[g.chunkId].push(a);
    if (g.endChunkId && g.endChunkId !== g.chunkId) {
      if (!byChunk[g.endChunkId]) byChunk[g.endChunkId] = [];
      byChunk[g.endChunkId].push(a);
    }
  }
  return { anchors, byChunk };
}

function buildHighlightsByChunk(highlights: UserHighlight[]): Record<string, UserHighlight[]> {
  const byChunk: Record<string, UserHighlight[]> = {};
  for (const h of highlights) {
    if (!byChunk[h.chunkId]) byChunk[h.chunkId] = [];
    byChunk[h.chunkId].push(h);
  }
  return byChunk;
}

type AskStore = {
  // Navigation & Multi-Book State
  viewMode: "library" | "reader";
  setViewMode: (mode: "library" | "reader") => void;
  activeBookId: string;
  setActiveBookId: (bookId: string) => void;
  openBook: (bookId: string) => void;
  booksCatalog: BookCatalogItem[];
  setBooksCatalog: (catalog: BookCatalogItem[]) => void;
  addBookToCatalog: (book: BookCatalogItem) => void;
  bookProgress: ProgressMap;
  updateBookProgress: (bookId: string, progress: { pct: number; chapter: string; chunkId: string }) => void;
  getBookStats: (bookId: string) => { highlightsCount: number; notesCount: number; pct: number; lastChapter: string };

  // Engine readiness state
  engineReady: boolean;
  refreshHealth: () => Promise<void>;
  stopHealthPolling: () => void;

  // Appearance state
  theme: ThemeName;
  pen: PenName;
  marker: MarkerColor;
  readSize: number;
  setTheme: (theme: ThemeName) => void;
  setPen: (pen: PenName) => void;
  setMarker: (marker: MarkerColor) => void;
  setReadSize: (size: number) => void;
  hydrateStore: () => void;

  // User highlights
  highlights: UserHighlight[];
  highlightsByChunk: Record<string, UserHighlight[]>;
  addHighlight: (h: Omit<UserHighlight, "id" | "createdAt">) => string;
  removeHighlight: (id: string) => void;

  // Gloss items
  glosses: GlossItem[];
  glossAnchors: GlossAnchor[];
  glossAnchorsByChunk: Record<string, GlossAnchor[]>;
  activeGlossId: string | null;
  hoveredGlossId: string | null;
  setActiveGloss: (id: string | null) => void;
  setHoveredGloss: (id: string | null) => void;
  removeGloss: (id: string) => void;
  toggleQuizKey: (glossId: string, turnId?: string) => void;
  stopGloss: (glossId?: string) => void;
  toggleMinimizeGloss: (id: string) => void;
  setGlossDragOffset: (id: string, offset: { x: number; y: number }) => void;
  setGlossWidth: (id: string, width: number) => void;
  setGlossHeight: (id: string, height: number | undefined) => void;
  removeTurn: (glossId: string, turnId: string) => void;
  returnSpot: { scrollY: number; label: string } | null;
  clearReturnSpot: () => void;

  // Actions
  askSelection: (
    question: string,
    passage: string,
    chunkId: string,
    chapter: string,
    heading?: string,
    at?: number,
    endChunkId?: string
  ) => string;
  submitWholeBook: (
    anchorChunkId: string,
    anchorChapter: string,
    questionOverride?: string,
    anchorHeading?: string
  ) => string | null;
  startQuiz: (anchorChunkId: string, anchorChapter: string) => string;
  askFollowUp: (glossId: string, followUpQuestion: string) => void;

  mode: "answer" | "ask";
  highlight: Highlight | null;
  thread: ThreadTurn[];

  setMode: (mode: "answer" | "ask") => void;
  clearHighlight: () => void;
  showCitation: (citation: {
    chunk_id: string;
    chapter: string;
    quote: string;
    at?: number;
    nonce?: number;
  }) => void;
};

function historyPayload(
  thread: ThreadTurn[]
): { question: string; answer: string }[] | undefined {
  if (thread.length === 0) return undefined;
  return thread.slice(-2).map(({ question, answer }) => ({ question, answer }));
}

let healthPollTimer: ReturnType<typeof setTimeout> | null = null;
let healthPollStart = 0;
let healthAbortController: AbortController | null = null;

export function stopHealthPolling(): void {
  if (healthPollTimer) {
    clearTimeout(healthPollTimer);
    healthPollTimer = null;
  }
  if (healthAbortController) {
    healthAbortController.abort();
    healthAbortController = null;
  }
  healthPollStart = 0;
}

export const useAsk = create<AskStore>((set, get) => {
  function syncActiveTurn(glosses: GlossItem[], activeGlossId: string | null) {
    const activeGloss = glosses.find((g) => g.id === activeGlossId) ?? null;
    const { anchors, byChunk } = buildGlossAnchors(glosses);

    set({
      glosses,
      glossAnchors: anchors,
      glossAnchorsByChunk: byChunk,
      activeGlossId,
      highlight:
        activeGlossId === get().activeGlossId && get().highlight?.nonce
          ? get().highlight
          : activeGloss && activeGloss.kind === "selection"
            ? {
                chunkId: activeGloss.chunkId,
                chapter: activeGloss.chapter,
                quote: activeGloss.quote,
                at: activeGloss.at,
              }
            : get().highlight,
    });
    saveBookState(get().activeBookId, get().highlights, glosses);
  }

  const startTurnStream = (glossId: string, turnId: string, payload: StreamPayload) =>
    runTurnStream({ get, set }, glossId, turnId, payload);

  return {
    // Navigation & Multi-Book State
    viewMode: "library",
    setViewMode: (viewMode) => set({ viewMode }),
    activeBookId: "fde",
    booksCatalog: [],
    bookProgress: {},

    engineReady: true,
    stopHealthPolling: () => {
      stopHealthPolling();
    },
    refreshHealth: async () => {
      stopHealthPolling();
      healthPollStart = Date.now();
      healthAbortController = new AbortController();
      const signal = healthAbortController.signal;

      const poll = async (delay = 500): Promise<void> => {
        // Hard cap: never block longer than 60s before enabling anyway
        if (Date.now() - healthPollStart >= 60000) {
          stopHealthPolling();
          set({ engineReady: true });
          return;
        }

        try {
          const h = await checkHealth(signal);
          // The engine's catalog is the truth: only books indexed on this machine.
          if (Array.isArray(h?.books)) get().setBooksCatalog(h.books);
          // Only an explicit ready: false from a reachable engine disables input
          // (missing fields = ready)
          if (h && h.ready === false) {
            set({ engineReady: false });
            // Poll with backoff: e.g. 500 ms -> 1000 ms -> 2000 ms cap
            const nextDelay = Math.min(delay * 2, 2000);
            healthPollTimer = setTimeout(() => {
              poll(nextDelay);
            }, delay);
            return;
          }
          // Reachable and ready !== false
          stopHealthPolling();
          set({ engineReady: true });
        } catch {
          // Failed /health fetch (network error / 500 / timeout) must NOT disable input
          stopHealthPolling();
          set({ engineReady: true });
        }
      };

      await poll(500);
    },

    setBooksCatalog: (booksCatalog) => {
      set({ booksCatalog });
      saveCatalog(booksCatalog);
    },

    addBookToCatalog: (book) => {
      const existing = get().booksCatalog;
      const filtered = existing.filter((b) => b.book_id !== book.book_id);
      const next = [...filtered, book];
      set({ booksCatalog: next });
      saveCatalog(next);
    },

    setActiveBookId: (bookId) => {
      const prevBookId = get().activeBookId;
      if (prevBookId === bookId) return;
      saveBookState(prevBookId, get().highlights, get().glosses);
      const nextState = loadBookState(bookId);
      const { anchors, byChunk: glossByChunk } = buildGlossAnchors(nextState.glosses);
      const hlByChunk = buildHighlightsByChunk(nextState.highlights);
      prefetchChunks(bookId);
      set({
        activeBookId: bookId,
        highlights: nextState.highlights,
        highlightsByChunk: hlByChunk,
        glosses: nextState.glosses,
        glossAnchors: anchors,
        glossAnchorsByChunk: glossByChunk,
        activeGlossId: null,
        highlight: null,
        thread: [],
      });
    },

    openBook: (bookId) => {
      const prevBookId = get().activeBookId;
      prefetchChunks(bookId);
      if (prevBookId !== bookId) {
        saveBookState(prevBookId, get().highlights, get().glosses);
        const nextState = loadBookState(bookId);
        const { anchors, byChunk: glossByChunk } = buildGlossAnchors(nextState.glosses);
        const hlByChunk = buildHighlightsByChunk(nextState.highlights);
        set({
          activeBookId: bookId,
          viewMode: "reader",
          highlights: nextState.highlights,
          highlightsByChunk: hlByChunk,
          glosses: nextState.glosses,
          glossAnchors: anchors,
          glossAnchorsByChunk: glossByChunk,
          activeGlossId: null,
          highlight: null,
          thread: [],
        });
      } else {
        set({ viewMode: "reader" });
      }
    },

    updateBookProgress: (bookId, { pct, chapter, chunkId }) => {
      const current = get().bookProgress;
      const next = {
        ...current,
        [bookId]: {
          pct,
          chapter,
          chunkId,
          lastReadAt: Date.now(),
        },
      };
      set({ bookProgress: next });
      saveProgress(next);
    },

    getBookStats: (bookId) => {
      const isCurrent = bookId === get().activeBookId;
      let highlightsCount = 0;
      let notesCount = 0;
      if (isCurrent) {
        highlightsCount = get().highlights.length;
        notesCount = get().glosses.length;
      } else {
        const state = loadBookState(bookId);
        highlightsCount = state.highlights.length;
        notesCount = state.glosses.length;
      }
      const prog = get().bookProgress[bookId] || { pct: 0, chapter: "", chunkId: "", lastReadAt: 0 };
      return {
        highlightsCount,
        notesCount,
        pct: prog.pct || 0,
        lastChapter: prog.chapter || "",
      };
    },

    // Appearance state
    theme: "night",
    pen: "vermilion",
    marker: "yellow",
    readSize: 19,

    setTheme: (theme) => {
      set({ theme });
      saveSettings({ theme, pen: get().pen, marker: get().marker, readSize: get().readSize });
    },
    setPen: (pen) => {
      set({ pen });
      saveSettings({ theme: get().theme, pen, marker: get().marker, readSize: get().readSize });
    },
    setMarker: (marker) => {
      set({ marker });
      saveSettings({ theme: get().theme, pen: get().pen, marker, readSize: get().readSize });
    },
    setReadSize: (rawSize) => {
      const readSize = Math.max(15, Math.min(26, rawSize));
      set({ readSize });
      saveSettings({ theme: get().theme, pen: get().pen, marker: get().marker, readSize });
    },

    hydrateStore: () => {
      if (typeof window === "undefined") return;
      const { theme, pen, marker, readSize } = loadSettings();

      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.pen = pen;
      document.documentElement.style.setProperty("--read-size", `${readSize}px`);

      // Determine book and view mode from URL
      let initialViewMode: "library" | "reader" = "library";
      let targetBookId = "fde";
      try {
        const params = new URLSearchParams(window.location.search);
        const bookParam = params.get("book");
        const modeParam = params.get("mode");
        if (bookParam) {
          targetBookId = bookParam;
          initialViewMode = "reader";
        } else if (modeParam === "reader") {
          initialViewMode = "reader";
        }
      } catch {
        // ignore
      }

      const catalog = loadCatalog();
      const progress = loadProgress();
      const bookState = loadBookState(targetBookId);
      const { anchors, byChunk: glossByChunk } = buildGlossAnchors(bookState.glosses);
      const hlByChunk = buildHighlightsByChunk(bookState.highlights);

      set({
        theme,
        pen,
        marker,
        readSize,
        viewMode: initialViewMode,
        activeBookId: targetBookId,
        booksCatalog: catalog,
        bookProgress: progress,
        highlights: bookState.highlights,
        highlightsByChunk: hlByChunk,
        glosses: bookState.glosses,
        glossAnchors: anchors,
        glossAnchorsByChunk: glossByChunk,
        engineReady: true,
      });

      get().refreshHealth();
      prefetchChunks(targetBookId);
    },

    // User highlights
    highlights: [],
    highlightsByChunk: {},
    addHighlight: (h) => {
      const current = get().highlights;
      // Check for overlap in same chunk
      const hMin = Math.min(h.start, h.end);
      const hMax = Math.max(h.start, h.end);
      const overlapIndex = current.findIndex(
        (existing) =>
          existing.chunkId === h.chunkId &&
          Math.max(Math.min(existing.start, existing.end), hMin) <
            Math.min(Math.max(existing.start, existing.end), hMax)
      );

      if (overlapIndex >= 0) {
        const existing = current[overlapIndex];
        if (existing.color === h.color) {
          // Same color -> remove / toggle off
          const next = current.filter((_, idx) => idx !== overlapIndex);
          set({
            highlights: next,
            highlightsByChunk: buildHighlightsByChunk(next),
          });
          saveBookState(get().activeBookId, next, get().glosses);
          saveHighlights(next);
          return "";
        } else {
          // Different color -> update color
          const next = current.map((item, idx) =>
            idx === overlapIndex ? { ...item, color: h.color } : item
          );
          set({
            highlights: next,
            highlightsByChunk: buildHighlightsByChunk(next),
          });
          saveBookState(get().activeBookId, next, get().glosses);
          saveHighlights(next);
          return existing.id;
        }
      }

      const id = `hl-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const newHl: UserHighlight = {
        ...h,
        id,
        createdAt: Date.now(),
      };
      const next = [...current, newHl];
      set({
        highlights: next,
        highlightsByChunk: buildHighlightsByChunk(next),
      });
      saveBookState(get().activeBookId, next, get().glosses);
      saveHighlights(next);
      return id;
    },

    removeHighlight: (id) => {
      const next = get().highlights.filter((h) => h.id !== id);
      set({
        highlights: next,
        highlightsByChunk: buildHighlightsByChunk(next),
      });
      saveBookState(get().activeBookId, next, get().glosses);
      saveHighlights(next);
    },

    // Gloss items
    glosses: [],
    glossAnchors: [],
    glossAnchorsByChunk: {},
    activeGlossId: null,
    hoveredGlossId: null,

    setActiveGloss: (id) => {
      if (id) {
        syncActiveTurn(patchGloss(get().glosses, id, { minimized: false }), id);
      } else {
        syncActiveTurn(get().glosses, null);
      }
    },

    setHoveredGloss: (id) => {
      set({ hoveredGlossId: id });
    },

    removeGloss: (id) => {
      abortFlights(id);
      const nextGlosses = get().glosses.filter((g) => g.id !== id);
      const nextActiveId = get().activeGlossId === id
        ? (nextGlosses.length > 0 ? nextGlosses[nextGlosses.length - 1].id : null)
        : get().activeGlossId;
      syncActiveTurn(nextGlosses, nextActiveId);
    },

    toggleQuizKey: (glossId, turnId) => {
      set((state) => ({
        glosses: patchGloss(state.glosses, glossId, (g) => {
          const targetId = turnId || g.turns[g.turns.length - 1]?.id || "";
          let nextQuote = g.quote;
          const nextTurns = mapTurns(g.turns, targetId, (t) => {
            const nextShow = !t.showQuizKey;
            if (nextShow) {
              nextQuote = t.body?.citations?.[0]?.quote || g.quote;
            }
            return { ...t, showQuizKey: nextShow };
          });
          return { ...g, quote: nextQuote, turns: nextTurns };
        }),
      }));
    },

    stopGloss: (glossId) => {
      const targetId = glossId ?? get().activeGlossId;
      abortFlights(targetId ?? undefined);
    },

    toggleMinimizeGloss: (id) => {
      set((state) => ({
        glosses: patchGloss(state.glosses, id, (g) => ({ ...g, minimized: !g.minimized })),
      }));
    },

    setGlossDragOffset: (id, offset) => {
      set((state) => ({ glosses: patchGloss(state.glosses, id, { dragOffset: offset }) }));
    },

    setGlossWidth: (id, width) => {
      set((state) => ({ glosses: patchGloss(state.glosses, id, { customWidth: width }) }));
    },

    setGlossHeight: (id, height) => {
      set((state) => ({ glosses: patchGloss(state.glosses, id, { customHeight: height }) }));
    },

    removeTurn: (glossId, turnId) => {
      set((state) => ({
        glosses: patchGloss(state.glosses, glossId, (g) => ({
          ...g,
          turns: g.turns.filter((t) => t.id !== turnId),
        })),
      }));
    },

    // Actions
    askSelection: (
      question,
      passage,
      chunkId,
      chapter,
      heading = "",
      at,
      endChunkId
    ) => {
      const text = passage.trim();
      if (!text) return "";
      const typed = question.trim();
      const glossId = `gloss-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const turnId = "turn-1";
      const isTyped = Boolean(typed);
      const turnMode = isTyped ? ("ask" as const) : ("explain" as const);
      const turnQuestion = isTyped ? typed : text;

      const turn: GlossTurn = {
        id: turnId,
        mode: turnMode,
        question: turnQuestion,
        status: "loading",
        streamText: "",
        resetting: false,
        body: null,
        error: "",
        elapsed: 0,
        firstToken: null,
        latency: null,
      };

      const item: GlossItem = {
        id: glossId,
        kind: "selection",
        chunkId,
        endChunkId,
        chapter,
        heading,
        quote: text,
        at,
        createdAt: Date.now(),
        turns: [turn],
      };

      const prevGlosses = get().glosses.map((g) => ({
        ...g,
        minimized: true,
      }));
      const nextGlosses = [...prevGlosses, item];
      syncActiveTurn(nextGlosses, glossId);

      const payload = isTyped
        ? {
            mode: "ask",
            question: typed,
            selection: text,
            chunk_id: chunkId,
            end_chunk_id: endChunkId || undefined,
            heading,
          }
        : {
            mode: "explain",
            selection: text,
            chunk_id: chunkId,
            end_chunk_id: endChunkId || undefined,
            heading,
          };

      startTurnStream(glossId, turnId, payload);
      return glossId;
    },

    submitWholeBook: (
      anchorChunkId,
      anchorChapter,
      questionOverride,
      anchorHeading = ""
    ) => {
      const state = get();
      const question = (questionOverride ?? "").trim();
      if (!question) return null;

      const glossId = `gloss-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const turnId = "turn-1";
      const turnMode = state.mode;

      const turn: GlossTurn = {
        id: turnId,
        mode: turnMode,
        question,
        status: "loading",
        streamText: "",
        resetting: false,
        body: null,
        error: "",
        elapsed: 0,
        firstToken: null,
        latency: null,
      };

      const item: GlossItem = {
        id: glossId,
        kind: "whole",
        chunkId: anchorChunkId,
        chapter: anchorChapter,
        heading: anchorHeading,
        quote: "",
        createdAt: Date.now(),
        turns: [turn],
      };

      const prevGlosses = state.glosses.map((g) => ({
        ...g,
        minimized: true,
      }));
      const nextGlosses = [...prevGlosses, item];
      syncActiveTurn(nextGlosses, glossId);

      const history = historyPayload(state.thread);
      const payload = {
        mode: turnMode,
        question,
        chunk_id: anchorChunkId || undefined,
        heading: anchorHeading || undefined,
        ...(history ? { history } : {}),
      };

      startTurnStream(glossId, turnId, payload);
      return glossId;
    },

    startQuiz: (anchorChunkId, anchorChapter) => {
      const glossId = `gloss-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const turnId = "turn-1";

      const turn: GlossTurn = {
        id: turnId,
        mode: "quiz",
        question: "Quiz",
        status: "loading",
        streamText: "",
        resetting: false,
        body: null,
        error: "",
        elapsed: 0,
        firstToken: null,
        latency: null,
        showQuizKey: false,
      };

      const item: GlossItem = {
        id: glossId,
        kind: "quiz",
        chunkId: anchorChunkId,
        chapter: anchorChapter,
        quote: "",
        createdAt: Date.now(),
        turns: [turn],
      };

      const prevGlosses = get().glosses.map((g) => ({
        ...g,
        minimized: true,
      }));
      const nextGlosses = [...prevGlosses, item];
      syncActiveTurn(nextGlosses, glossId);

      startTurnStream(glossId, turnId, {
        mode: "quiz",
        chunk_id: anchorChunkId || undefined,
      });
      return glossId;
    },

    askFollowUp: (glossId, followUpQuestion) => {
      const q = followUpQuestion.trim();
      if (!q) return;

      const state = get();
      const targetGloss = state.glosses.find((g) => g.id === glossId);
      if (!targetGloss) return;

      const finished = targetGloss.turns.filter(
        (t) => (t.status === "done" || t.status === "refused") && t.body !== null
      );
      const history = finished.slice(-2).map((t) => ({
        question: t.mode === "explain" && !t.question ? targetGloss.quote : t.question,
        answer: t.body!.answer,
      }));

      const lastFinished = finished[finished.length - 1];
      const lastCitedChunkId = lastFinished?.body?.citations?.[0]?.chunk_id;

      const turnId = `turn-${targetGloss.turns.length + 1}`;
      const turnMode =
        targetGloss.kind === "selection"
          ? (targetGloss.turns[0]?.mode === "explain" ? "ask" : state.mode)
          : state.mode;

      const turn: GlossTurn = {
        id: turnId,
        mode: turnMode,
        question: q,
        status: "loading",
        streamText: "",
        resetting: false,
        body: null,
        error: "",
        elapsed: 0,
        firstToken: null,
        latency: null,
      };

      const nextGlosses = patchGloss(state.glosses, glossId, (g) => ({
        ...g,
        turns: [...g.turns, turn],
      }));

      syncActiveTurn(nextGlosses, glossId);

      const payload = {
        mode: turnMode,
        question: q,
        selection:
          targetGloss.kind === "selection"
            ? targetGloss.quote || undefined
            : undefined,
        chunk_id: lastCitedChunkId || targetGloss.chunkId || undefined,
        end_chunk_id: targetGloss.endChunkId || undefined,
        heading: targetGloss.heading || undefined,
        ...(history.length > 0 ? { history } : {}),
      };

      startTurnStream(glossId, turnId, payload);
    },

    mode: "answer",
    highlight: null,
    returnSpot: null,
    clearReturnSpot: () => set({ returnSpot: null }),
    thread: [],

    setMode: (mode) => set({ mode }),
    clearHighlight: () => set({ highlight: null }),

    showCitation: (citation) => {
      let returnSpot: { scrollY: number; label: string } | null = null;
      if (typeof window !== "undefined") {
        const currentY = window.scrollY;
        const activeGloss = get().glosses.find((g) => g.id === get().activeGlossId);
        const originChap = activeGloss?.chapter
          ? `Ch. ${activeGloss.chapter.replace(/^ch/i, "")}`
          : "previous spot";
        returnSpot = { scrollY: currentY, label: originChap };
      }
      set({
        returnSpot,
        highlight: {
          chunkId: citation.chunk_id,
          chapter: citation.chapter,
          quote: citation.quote,
          at: citation.at,
          nonce: citation.nonce ?? Date.now(),
        },
      });
    },
  };
});
