import { create } from "zustand";
import { askStream, type AnswerBody, type BookCatalogItem, type AskRequest } from "./engine";
import type { MarkerColor, UserHighlight } from "./anchor";

export const DEFAULT_BOOKS: BookCatalogItem[] = [
  {
    book_id: "fde",
    title: "Fundamentals of Data Engineering",
    author: "Joe Reis & Matt Housley",
    chapter_count: 11,
    chunk_count: 1065,
    figure_count: 111,
  },
  {
    book_id: "ddia",
    title: "Designing Data-Intensive Applications",
    author: "Martin Kleppmann",
    chapter_count: 12,
    chunk_count: 1280,
    figure_count: 98,
  },
  {
    book_id: "quantization",
    title: "Quantization and Fast Inference",
    author: "Tim Dettmers & Elias Frantar",
    chapter_count: 7,
    chunk_count: 502,
    figure_count: 42,
  },
];

export type ThemeName = "night" | "paper" | "sepia" | "snow" | "ink";
export type PenName = "vermilion" | "cobalt" | "moss" | "graphite";
export type { MarkerColor, UserHighlight } from "./anchor";

export type Status =
  | "idle"
  | "loading"
  | "streaming"
  | "done"
  | "refused"
  | "stopped"
  | "error";

export type Highlight = {
  chunkId: string;
  chapter: string;
  quote: string;
  at?: number;
  nonce?: number;
};

export type Anchor = {
  chunkId: string;
  chapter: string;
  quote: string;
  question: string;
};

export type ThreadTurn = {
  question: string;
  answer: string;
  refused: boolean;
  citations: { chunk_id: string; chapter: string; quote: string }[];
};

export type GlossTurn = {
  id: string;
  mode: "answer" | "ask" | "explain" | "quiz";
  question: string;
  status: Status;
  streamText: string;
  resetting: boolean;
  body: AnswerBody | null;
  error: string;
  elapsed: number;
  firstToken: number | null;
  latency: number | null;
  showQuizKey?: boolean;
};

export type GlossItem = {
  id: string;
  kind: "selection" | "whole" | "quiz";
  chunkId: string;
  endChunkId?: string;
  chapter: string;
  heading?: string;
  quote: string;
  at?: number;
  createdAt: number;
  turns: GlossTurn[];
  minimized?: boolean;
  dragOffset?: { x: number; y: number };
  customWidth?: number;
  customHeight?: number;
};

type InFlightTurn = {
  controller: AbortController;
  ticker: ReturnType<typeof setInterval>;
  pacerTimer: ReturnType<typeof setInterval> | null;
  startedAt: number;
};

const inFlightMap = new Map<string, InFlightTurn>();

function cleanupFlight(flight: InFlightTurn) {
  if (flight.pacerTimer !== null) {
    clearInterval(flight.pacerTimer);
    flight.pacerTimer = null;
  }
  clearInterval(flight.ticker);
  flight.controller.abort();
}

function flightKey(glossId: string, turnId: string) {
  return `${glossId}:${turnId}`;
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
  bookProgress: Record<string, { pct: number; chapter: string; chunkId: string; lastReadAt: number }>;
  updateBookProgress: (bookId: string, progress: { pct: number; chapter: string; chunkId: string }) => void;
  getBookStats: (bookId: string) => { highlightsCount: number; notesCount: number; pct: number; lastChapter: string };

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
  addHighlight: (h: Omit<UserHighlight, "id" | "createdAt">) => string;
  removeHighlight: (id: string) => void;

  // Gloss items
  glosses: GlossItem[];
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

  // Top-level backwards-compatible fields
  mode: "answer" | "ask";
  question: string;
  status: Status;
  streamText: string;
  resetting: boolean;
  body: AnswerBody | null;
  error: string;
  elapsed: number;
  firstToken: number | null;
  latency: number | null;
  highlight: Highlight | null;
  highlightNote: string;
  anchor: Anchor | null;
  anchored: boolean;
  marginRoom: boolean;
  thread: ThreadTurn[];
  busyNote: string;

  setMode: (mode: "answer" | "ask") => void;
  setQuestion: (question: string) => void;
  setMarginRoom: (room: boolean) => void;
  setHighlightNote: (note: string) => void;
  clearHighlight: () => void;
  clearThread: () => void;
  showCitation: (citation: {
    chunk_id: string;
    chapter: string;
    quote: string;
    at?: number;
    nonce?: number;
  }) => void;
  stop: () => void;
  submit: () => void;
};

function saveSettings(settings: { theme: ThemeName; pen: PenName; marker: MarkerColor; readSize: number }) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("atb-settings", JSON.stringify(settings));
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.pen = settings.pen;
    document.documentElement.style.setProperty("--read-size", `${settings.readSize}px`);
  } catch {
    // ignore quota/storage errors
  }
}

function saveHighlights(highlights: UserHighlight[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("atb-highlights", JSON.stringify(highlights));
  } catch {
    // ignore quota/storage errors
  }
}

function saveBookState(bookId: string, highlights: UserHighlight[], glosses: GlossItem[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(`nekohon-state-${bookId}`, JSON.stringify({ highlights, glosses }));
  } catch {
    // ignore quota/storage errors
  }
}

function loadBookState(bookId: string): { highlights: UserHighlight[]; glosses: GlossItem[] } {
  if (typeof window === "undefined") return { highlights: [], glosses: [] };
  try {
    const raw = localStorage.getItem(`nekohon-state-${bookId}`);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        highlights: Array.isArray(parsed.highlights) ? parsed.highlights : [],
        glosses: Array.isArray(parsed.glosses) ? parsed.glosses : [],
      };
    }
    // Migration: if book is fde and legacy atb-highlights exists, migrate it
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
  } catch {
    // ignore
  }
  return { highlights: [], glosses: [] };
}

function saveProgress(progress: Record<string, { pct: number; chapter: string; chunkId: string; lastReadAt: number }>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("nekohon-progress", JSON.stringify(progress));
  } catch {
    // ignore
  }
}

function loadProgress(): Record<string, { pct: number; chapter: string; chunkId: string; lastReadAt: number }> {
  if (typeof window === "undefined") return {};
  try {
    const raw = localStorage.getItem("nekohon-progress");
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore
  }
  return {};
}

function saveCatalog(catalog: BookCatalogItem[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem("nekohon-catalog", JSON.stringify(catalog));
  } catch {
    // ignore
  }
}

function loadCatalog(): BookCatalogItem[] {
  if (typeof window === "undefined") return DEFAULT_BOOKS;
  try {
    const raw = localStorage.getItem("nekohon-catalog");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        const map = new Map<string, BookCatalogItem>();
        for (const b of DEFAULT_BOOKS) map.set(b.book_id, b);
        for (const b of parsed) map.set(b.book_id, { ...(map.get(b.book_id) || {}), ...b });
        return Array.from(map.values());
      }
    }
  } catch {
    // ignore
  }
  return DEFAULT_BOOKS;
}

function historyPayload(
  thread: ThreadTurn[]
): { question: string; answer: string }[] | undefined {
  if (thread.length === 0) return undefined;
  return thread.slice(-2).map(({ question, answer }) => ({ question, answer }));
}

export const useAsk = create<AskStore>((set, get) => {
  function syncActiveTurn(glosses: GlossItem[], activeGlossId: string | null) {
    const activeGloss = glosses.find((g) => g.id === activeGlossId) ?? null;
    const activeTurn = activeGloss && activeGloss.turns.length > 0
      ? activeGloss.turns[activeGloss.turns.length - 1]
      : null;

    set({
      glosses,
      activeGlossId,
      status: activeTurn ? activeTurn.status : "idle",
      streamText: activeTurn ? activeTurn.streamText : "",
      resetting: activeTurn ? activeTurn.resetting : false,
      body: activeTurn ? activeTurn.body : null,
      error: activeTurn ? activeTurn.error : "",
      elapsed: activeTurn ? activeTurn.elapsed : 0,
      firstToken: activeTurn ? activeTurn.firstToken : null,
      latency: activeTurn ? activeTurn.latency : null,
      anchor:
        activeGloss && activeGloss.kind === "selection"
          ? {
              chunkId: activeGloss.chunkId,
              chapter: activeGloss.chapter,
              quote: activeGloss.quote,
              question: activeTurn ? activeTurn.question : "",
            }
          : null,
      anchored: activeGloss ? activeGloss.kind === "selection" : false,
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

  function startTurnStream(
    glossId: string,
    turnId: string,
    payload: {
      mode: string;
      book_id?: string;
      question?: string;
      selection?: string;
      chunk_id?: string;
      end_chunk_id?: string;
      heading?: string;
      history?: { question: string; answer: string }[];
    }
  ) {
    // Preemptively cancel any existing in-flight turns to eliminate serial Ollama blocking
    for (const [flightKey, entry] of inFlightMap.entries()) {
      cleanupFlight(entry);
      inFlightMap.delete(flightKey);
    }

    // Mark any still loading or streaming turns across all glosses as "stopped"
    set((state) => ({
      glosses: state.glosses.map((g) => ({
        ...g,
        turns: g.turns.map((t) =>
          g.id === glossId && t.id === turnId
            ? t
            : t.status === "loading" || t.status === "streaming"
              ? { ...t, status: "stopped" as Status }
              : t
        ),
      })),
    }));

    const key = flightKey(glossId, turnId);
    const controller = new AbortController();
    const startedAt = performance.now();
    const ticker = setInterval(() => {
      const elapsed = (performance.now() - startedAt) / 1000;
      set((state) => {
        const nextGlosses = state.glosses.map((g) => {
          if (g.id !== glossId) return g;
          return {
            ...g,
            turns: g.turns.map((t) => (t.id === turnId ? { ...t, elapsed } : t)),
          };
        });
        const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
        const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
        return {
          glosses: nextGlosses,
          elapsed: activeTurn ? elapsed : state.elapsed,
        };
      });
    }, 200);

    const flight: InFlightTurn = {
      controller,
      ticker,
      pacerTimer: null,
      startedAt,
    };
    inFlightMap.set(key, flight);

    let targetText = "";
    let displayedText = "";
    let finalResult: AnswerBody | null = null;

    const stopPacer = () => {
      if (flight.pacerTimer !== null) {
        clearInterval(flight.pacerTimer);
        flight.pacerTimer = null;
      }
    };

    const pacerStep = () => {
      if (targetText.startsWith("[")) {
        const nlIdx = targetText.indexOf("\n");
        if (nlIdx === -1) {
          displayedText = targetText;
        } else if (displayedText.length < nlIdx + 1) {
          displayedText = targetText.slice(0, nlIdx + 1);
        }
      }

      if (displayedText.length < targetText.length) {
        const remaining = targetText.slice(displayedText.length);
        const backlog = targetText.length - displayedText.length;
        let step = 0;
        const wordMatch = remaining.match(/^\s*\S+\s*/);
        if (backlog > 40) {
          const cap = Math.min(remaining.length, Math.max(12, Math.ceil(backlog / 5)));
          const spaceIdx = remaining.indexOf(" ", cap);
          if (spaceIdx !== -1 && spaceIdx - cap < 15) {
            step = spaceIdx + 1;
          } else {
            const twoWords = remaining.match(/^(\s*\S+\s*){1,2}/);
            step = twoWords ? twoWords[0].length : cap;
          }
        } else {
          step = wordMatch ? wordMatch[0].length : Math.min(remaining.length, 6);
        }
        if (step <= 0) step = Math.min(remaining.length, 1);
        displayedText += remaining.slice(0, step);

        set((state) => {
          const nextGlosses = state.glosses.map((g) => {
            if (g.id !== glossId) return g;
            return {
              ...g,
              turns: g.turns.map((t) => {
                if (t.id !== turnId) return t;
                return {
                  ...t,
                  status: "streaming" as Status,
                  streamText: displayedText,
                  resetting: false,
                  firstToken: t.firstToken ?? (performance.now() - startedAt) / 1000,
                };
              }),
            };
          });
          const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
          const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
          return {
            glosses: nextGlosses,
            status: activeTurn ? "streaming" : state.status,
            streamText: activeTurn ? displayedText : state.streamText,
            resetting: activeTurn ? false : state.resetting,
            firstToken: activeTurn ? activeTurn.firstToken : state.firstToken,
          };
        });
      } else if (finalResult !== null) {
        stopPacer();
        clearInterval(flight.ticker);
        inFlightMap.delete(key);

        const latency = (performance.now() - startedAt) / 1000;
        const body = finalResult;
        const isRefused = body.refused;

        set((state) => {
          const targetGloss = state.glosses.find((g) => g.id === glossId);
          const targetTurn = targetGloss?.turns.find((t) => t.id === turnId);

          const nextGlosses = state.glosses.map((g) => {
            if (g.id !== glossId) return g;
            const nextChunkId =
              g.kind === "quiz" && body.citations?.[0]?.chunk_id
                ? body.citations[0].chunk_id
                : g.chunkId;
            const nextChapter =
              g.kind === "quiz" && body.citations?.[0]?.chapter
                ? String(body.citations[0].chapter)
                : g.chapter;
            return {
              ...g,
              chunkId: nextChunkId,
              chapter: nextChapter,
              turns: g.turns.map((t) => {
                if (t.id !== turnId) return t;
                return {
                  ...t,
                  status: (isRefused ? "refused" : "done") as Status,
                  body,
                  streamText: "",
                  latency,
                };
              }),
            };
          });

          let nextThread = state.thread;
          if (targetGloss?.kind === "whole" && targetTurn?.question) {
            nextThread = [
              ...state.thread,
              {
                question: targetTurn.question,
                answer: body.answer,
                refused: body.refused,
                citations: body.citations,
              },
            ];
          }

          const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
          const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);

          return {
            glosses: nextGlosses,
            thread: nextThread,
            busyNote: "",
            status: activeTurn ? (isRefused ? "refused" : "done") : state.status,
            body: activeTurn ? body : state.body,
            streamText: activeTurn ? "" : state.streamText,
            latency: activeTurn ? latency : state.latency,
          };
        });
      }
    };

    const ensurePacerRunning = () => {
      if (flight.pacerTimer === null) {
        flight.pacerTimer = setInterval(pacerStep, 20);
      }
    };

    const requestPayload: AskRequest = {
      ...payload,
      book_id: payload.book_id || get().activeBookId,
    };

    askStream(
      requestPayload,
      {
        onToken: (text) => {
          targetText += text;
          ensurePacerRunning();
        },
        onReset: () => {
          const quoteMatch = targetText.match(
            /^(\[(?:Ch|Chapter)\.?\s*[^\]]+\]\s*["\u201c][^"\u201d\n]+["\u201d]?)/i
          );
          if (quoteMatch) {
            const preservedQuoteLine = quoteMatch[1] + "\n";
            targetText = preservedQuoteLine;
            if (displayedText.length > preservedQuoteLine.length) {
              displayedText = preservedQuoteLine;
            }
            set((state) => {
              const nextGlosses = state.glosses.map((g) => {
                if (g.id !== glossId) return g;
                return {
                  ...g,
                  turns: g.turns.map((t) => {
                    if (t.id !== turnId) return t;
                    return {
                      ...t,
                      streamText: displayedText,
                      resetting: false,
                    };
                  }),
                };
              });
              const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
              const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
              return {
                glosses: nextGlosses,
                streamText: activeTurn ? displayedText : state.streamText,
                resetting: false,
              };
            });
            ensurePacerRunning();
          } else {
            targetText = "";
            displayedText = "";
            set((state) => {
              const nextGlosses = state.glosses.map((g) => {
                if (g.id !== glossId) return g;
                return {
                  ...g,
                  turns: g.turns.map((t) => {
                    if (t.id !== turnId) return t;
                    return {
                      ...t,
                      streamText: "",
                      resetting: t.streamText.length > 0,
                    };
                  }),
                };
              });
              const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
              const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
              return {
                glosses: nextGlosses,
                streamText: activeTurn ? "" : state.streamText,
                resetting: activeTurn ? activeTurn.resetting : state.resetting,
              };
            });
          }
        },
        onFinal: (body) => {
          finalResult = body;
          if (body.answer && !body.refused && payload.mode !== "quiz") {
            if (targetText.length === 0) {
              targetText = body.answer;
            } else if (
              body.answer.startsWith(targetText.trimEnd()) &&
              body.answer.length > targetText.length
            ) {
              targetText = body.answer;
            }
          }
          ensurePacerRunning();
        },
        onError: (message) => {
          stopPacer();
          clearInterval(flight.ticker);
          inFlightMap.delete(key);
          const latency = (performance.now() - startedAt) / 1000;

          set((state) => {
            const nextGlosses = state.glosses.map((g) => {
              if (g.id !== glossId) return g;
              return {
                ...g,
                turns: g.turns.map((t) => {
                  if (t.id !== turnId) return t;
                  return {
                    ...t,
                    status: "error" as Status,
                    error: message,
                    streamText: "",
                    latency,
                  };
                }),
              };
            });
            const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
            const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
            return {
              glosses: nextGlosses,
              busyNote: "",
              status: activeTurn ? "error" : state.status,
              error: activeTurn ? message : state.error,
              streamText: activeTurn ? "" : state.streamText,
              latency: activeTurn ? latency : state.latency,
            };
          });
        },
      },
      controller.signal
    ).catch((err: unknown) => {
      stopPacer();
      clearInterval(flight.ticker);
      inFlightMap.delete(key);
      const latency = (performance.now() - startedAt) / 1000;

      const name = (err as { name?: string })?.name;
      const isAbort = name === "AbortError";

      set((state) => {
        const nextGlosses = state.glosses.map((g) => {
          if (g.id !== glossId) return g;
          return {
            ...g,
            turns: g.turns.map((t) => {
              if (t.id !== turnId) return t;
              return {
                ...t,
                status: (isAbort ? "stopped" : "error") as Status,
                error: isAbort ? "" : "Engine unreachable — start it on :8000, then ask again.",
                streamText: "",
                latency: isAbort ? latency : null,
              };
            }),
          };
        });
        const activeGloss = nextGlosses.find((g) => g.id === state.activeGlossId);
        const activeTurn = activeGloss?.turns.find((t) => t.id === turnId);
        return {
          glosses: nextGlosses,
          busyNote: "",
          status: activeTurn ? (isAbort ? "stopped" : "error") : state.status,
          error: activeTurn && !isAbort ? "Engine unreachable — start it on :8000, then ask again." : state.error,
          streamText: activeTurn ? "" : state.streamText,
          latency: activeTurn ? (isAbort ? latency : null) : state.latency,
        };
      });
    });
  }

  return {
    // Navigation & Multi-Book State
    viewMode: "library",
    setViewMode: (viewMode) => set({ viewMode }),
    activeBookId: "fde",
    booksCatalog: DEFAULT_BOOKS,
    bookProgress: {},

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
      set({
        activeBookId: bookId,
        highlights: nextState.highlights,
        glosses: nextState.glosses,
        activeGlossId: null,
        highlight: null,
        anchor: null,
        thread: [],
        error: "",
        status: "idle",
        streamText: "",
      });
    },

    openBook: (bookId) => {
      const prevBookId = get().activeBookId;
      if (prevBookId !== bookId) {
        saveBookState(prevBookId, get().highlights, get().glosses);
        const nextState = loadBookState(bookId);
        set({
          activeBookId: bookId,
          viewMode: "reader",
          highlights: nextState.highlights,
          glosses: nextState.glosses,
          activeGlossId: null,
          highlight: null,
          anchor: null,
          thread: [],
          error: "",
          status: "idle",
          streamText: "",
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
      let theme: ThemeName = "night";
      let pen: PenName = "vermilion";
      let marker: MarkerColor = "yellow";
      let readSize = 19;

      try {
        const rawSettings = localStorage.getItem("atb-settings");
        if (rawSettings) {
          const parsed = JSON.parse(rawSettings);
          if (parsed.theme) theme = parsed.theme;
          if (parsed.pen) pen = parsed.pen;
          if (parsed.marker) marker = parsed.marker;
          if (typeof parsed.readSize === "number") {
            readSize = Math.max(15, Math.min(26, parsed.readSize));
          }
        }
      } catch {
        // ignore
      }

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
        glosses: bookState.glosses,
      });
    },

    // User highlights
    highlights: [],
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
          set({ highlights: next });
          saveBookState(get().activeBookId, next, get().glosses);
          saveHighlights(next);
          return "";
        } else {
          // Different color -> update color
          const next = current.map((item, idx) =>
            idx === overlapIndex ? { ...item, color: h.color } : item
          );
          set({ highlights: next });
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
      set({ highlights: next });
      saveBookState(get().activeBookId, next, get().glosses);
      saveHighlights(next);
      return id;
    },

    removeHighlight: (id) => {
      const next = get().highlights.filter((h) => h.id !== id);
      set({ highlights: next });
      saveBookState(get().activeBookId, next, get().glosses);
      saveHighlights(next);
    },

    // Gloss items
    glosses: [],
    activeGlossId: null,
    hoveredGlossId: null,

    setActiveGloss: (id) => {
      if (id) {
        const next = get().glosses.map((g) =>
          g.id === id ? { ...g, minimized: false } : g
        );
        syncActiveTurn(next, id);
      } else {
        syncActiveTurn(get().glosses, null);
      }
    },

    setHoveredGloss: (id) => {
      set({ hoveredGlossId: id });
    },

    removeGloss: (id) => {
      // Abort any in-flight turns for this gloss
      for (const [key, flight] of inFlightMap.entries()) {
        if (key.startsWith(`${id}:`)) {
          cleanupFlight(flight);
          inFlightMap.delete(key);
        }
      }
      const nextGlosses = get().glosses.filter((g) => g.id !== id);
      const nextActiveId = get().activeGlossId === id
        ? (nextGlosses.length > 0 ? nextGlosses[nextGlosses.length - 1].id : null)
        : get().activeGlossId;
      syncActiveTurn(nextGlosses, nextActiveId);
    },

    toggleQuizKey: (glossId, turnId) => {
      set((state) => ({
        glosses: state.glosses.map((g) => {
          if (g.id !== glossId) return g;
          let nextQuote = g.quote;
          const nextTurns = g.turns.map((t, idx) => {
            if (turnId ? t.id === turnId : idx === g.turns.length - 1) {
              const nextShow = !t.showQuizKey;
              if (nextShow) {
                nextQuote = t.body?.citations?.[0]?.quote || g.quote;
              }
              return { ...t, showQuizKey: nextShow };
            }
            return t;
          });
          return {
            ...g,
            quote: nextQuote,
            turns: nextTurns,
          };
        }),
      }));
    },

    stopGloss: (glossId) => {
      const targetId = glossId ?? get().activeGlossId;
      for (const [key, flight] of inFlightMap.entries()) {
        if (!targetId || key.startsWith(`${targetId}:`)) {
          cleanupFlight(flight);
          inFlightMap.delete(key);
        }
      }
    },

    toggleMinimizeGloss: (id) => {
      set((state) => ({
        glosses: state.glosses.map((g) =>
          g.id === id ? { ...g, minimized: !g.minimized } : g
        ),
      }));
    },

    setGlossDragOffset: (id, offset) => {
      set((state) => ({
        glosses: state.glosses.map((g) =>
          g.id === id ? { ...g, dragOffset: offset } : g
        ),
      }));
    },

    setGlossWidth: (id, width) => {
      set((state) => ({
        glosses: state.glosses.map((g) =>
          g.id === id ? { ...g, customWidth: width } : g
        ),
      }));
    },

    setGlossHeight: (id, height) => {
      set((state) => ({
        glosses: state.glosses.map((g) =>
          g.id === id ? { ...g, customHeight: height } : g
        ),
      }));
    },

    removeTurn: (glossId, turnId) => {
      set((state) => ({
        glosses: state.glosses.map((g) => {
          if (g.id !== glossId) return g;
          return {
            ...g,
            turns: g.turns.filter((t) => t.id !== turnId),
          };
        }),
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
      const question = (questionOverride ?? state.question).trim();
      if (!question) return null;

      set({ question: "" });
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

      const nextGlosses = state.glosses.map((g) => {
        if (g.id !== glossId) return g;
        return {
          ...g,
          turns: [...g.turns, turn],
        };
      });

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

    // Top-level backwards-compatible fields
    mode: "answer",
    question: "",
    status: "idle",
    streamText: "",
    resetting: false,
    body: null,
    error: "",
    elapsed: 0,
    firstToken: null,
    latency: null,
    highlight: null,
    highlightNote: "",
    returnSpot: null,
    clearReturnSpot: () => set({ returnSpot: null }),
    anchor: null,
    anchored: false,
    marginRoom: false,
    thread: [],
    busyNote: "",

    setMode: (mode) => set({ mode }),
    setQuestion: (question) => set({ question }),
    setMarginRoom: (marginRoom) => set({ marginRoom }),
    setHighlightNote: (highlightNote) => set({ highlightNote }),
    clearHighlight: () => set({ highlight: null, highlightNote: "", anchor: null }),
    clearThread: () => set({ thread: [] }),

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
        highlightNote: "",
      });
    },

    stop: () => {
      get().stopGloss();
    },

    submit: () => {
      const q = get().question.trim();
      if (!q) return;
      get().submitWholeBook(get().anchor?.chunkId || "", get().anchor?.chapter || "");
    },
  };
});
