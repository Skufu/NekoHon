"use client";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import dynamic from "next/dynamic";
import TopBar from "@/components/TopBar";
import Rail from "@/components/Rail";
import Margin from "@/components/Margin";
import Lens from "@/components/Lens";
import Composer from "@/components/Composer";

const LibraryView = dynamic(() => import("@/components/LibraryView"), {
  ssr: false,
});

const EMPTY_ARRAY: never[] = [];
import { engineUrl, fetchChunks, type Chunk, type ChunksPayload } from "@/lib/engine";
import { quotePattern } from "@/lib/quote";
import {
  splitParagraphSegments,
  findQuoteSpan,
  findQuoteSpanForRole,
  isHeadingOffset,
  decodeHeadingOffset,
  type Segment,
} from "@/lib/anchor";
import { useAsk } from "@/lib/store";

function paragraphList(text: string): string[] {
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** Cubic-bezier ease-out for citation jump scrolling */
function easeOut(t: number) {
  const x1 = 0.23;
  const y1 = 1;
  const x2 = 0.32;
  const y2 = 1;
  let x = t;
  for (let i = 0; i < 6; i++) {
    const cx = 3 * x1;
    const bx = 3 * (x2 - x1) - cx;
    const ax = 1 - cx - bx;
    const f = ((ax * x + bx) * x + cx) * x - t;
    const d = (3 * ax * x + 2 * bx) * x + cx;
    if (Math.abs(d) < 1e-6) break;
    x -= f / d;
  }
  const cy = 3 * y1;
  const by = 3 * (y2 - y1) - cy;
  const ay = 1 - cy - by;
  return ((ay * x + by) * x + cy) * x;
}

function animateScrollTo(targetY: number, ms = 520) {
  if (typeof window === "undefined") return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    window.scrollTo({ top: targetY, behavior: "instant" });
    return;
  }
  const from = window.scrollY;
  const distance = targetY - from;
  const started = performance.now();
  const ease = (t: number) =>
    t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  const step = (now: number) => {
    const t = Math.min(1, (now - started) / ms);
    window.scrollTo({ top: from + distance * ease(t), behavior: "instant" });
    if (t < 1) {
      requestAnimationFrame(step);
    }
  };
  requestAnimationFrame(step);
}

function scrollingBox(start: Element): Element {
  let node: Element | null = start.parentElement;
  while (node) {
    const style = getComputedStyle(node);
    if (
      (style.overflowY === "auto" || style.overflowY === "scroll") &&
      node.scrollHeight > node.clientHeight
    ) {
      return node;
    }
    node = node.parentElement;
  }
  return document.scrollingElement ?? document.documentElement;
}

function centerDelta(target: Element, box: Element) {
  const mark = target.getBoundingClientRect();
  const view =
    box === document.scrollingElement || box === document.documentElement
      ? { top: 0, height: window.innerHeight }
      : box.getBoundingClientRect();
  return mark.top - view.top - (view.height - mark.height) / 2;
}

/** Fallback markQuote */
function markQuote(
  paragraphs: string[],
  quote: string,
  at?: number
): { parts: { text: string; mark: [number, number] | null }[]; found: boolean } {
  const plain = paragraphs.map((text) => ({
    text,
    mark: null as [number, number] | null,
  }));
  if (!quote.trim()) return { parts: plain, found: false };
  const raw = paragraphs.join("\n");
  const pattern = quotePattern(quote);
  const hits: { index: number; length: number }[] = [];
  for (const match of raw.matchAll(new RegExp(pattern.source, "g"))) {
    if (match.index !== undefined) {
      hits.push({ index: match.index, length: match[0].length });
    }
  }
  if (!hits.length) return { parts: plain, found: false };
  const hit =
    at == null
      ? hits[0]
      : hits.reduce((best, item) =>
          Math.abs(item.index - at) < Math.abs(best.index - at) ? item : best
        );
  const start = hit.index;
  const end = start + hit.length;
  let cursor = 0;
  const parts = paragraphs.map((text) => {
    const from = cursor;
    const to = cursor + text.length;
    cursor = to + 1;
    const markFrom = Math.max(start, from) - from;
    const markTo = Math.min(end, to) - from;
    return markFrom < markTo
      ? { text, mark: [markFrom, markTo] as [number, number] }
      : { text, mark: null };
  });
  return { parts, found: true };
}

export type ReaderProps = {
  payload?: ChunksPayload | null;
  loadError?: string;
};

export default function Reader({
  payload: initialPayload = null,
  loadError: initialLoadError = "",
}: ReaderProps = {}) {
  const viewMode = useAsk((s) => s.viewMode);
  const activeBookId = useAsk((s) => s.activeBookId);
  const updateBookProgress = useAsk((s) => s.updateBookProgress);
  const setBooksCatalog = useAsk((s) => s.setBooksCatalog);
  const booksCatalog = useAsk((s) => s.booksCatalog);

  const [payload, setPayload] = useState<ChunksPayload | null>(initialPayload);
  const [loadError, setLoadError] = useState(initialLoadError);
  const [loading, setLoading] = useState(false);

  // Re-fetch /chunks?book_id=${activeBookId} whenever activeBookId changes
  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setLoadError("");

    fetchChunks(activeBookId, ac.signal)
      .then((data) => {
        setPayload(data);
        setLoading(false);
        if (data.books && Array.isArray(data.books)) {
          setBooksCatalog(data.books);
        }
      })
      .catch((error: unknown) => {
        if (ac.signal.aborted) return;
        setLoading(false);
        const detail = error instanceof Error ? error.message : "unknown error";
        setLoadError(
          `Could not load the book (${activeBookId}): ${detail} — is the engine running on :8000?`
        );
      });

    return () => ac.abort();
  }, [activeBookId, setBooksCatalog]);

  const highlight = useAsk((s) => s.highlight);
  const clearHighlight = useAsk((s) => s.clearHighlight);
  const setActiveGloss = useAsk((s) => s.setActiveGloss);
  const returnSpot = useAsk((s) => s.returnSpot);
  const clearReturnSpot = useAsk((s) => s.clearReturnSpot);

  const readerRef = useRef<HTMLElement | null>(null);
  const textRef = useRef<HTMLDivElement | null>(null);

  const [wide, setWide] = useState(true);
  const [activeChunkId, setActiveChunkId] = useState("");
  const [activeChapter, setActiveChapter] = useState("");
  const [activeHeading, setActiveHeading] = useState("");
  const [scrollProgress, setScrollProgress] = useState(0);
  const [viewportRatio, setViewportRatio] = useState(0.2);

  // Wide screen query (1080px)
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1080px)");
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const chunkMap = useMemo(() => {
    if (!payload) return new Map<string, Chunk>();
    return new Map(payload.chunks.map((c) => [c.chunk_id, c]));
  }, [payload]);

  const restoredRef = useRef<string | null>(null);

  // Restore saved reading progress on initial book load
  useEffect(() => {
    if (!payload || payload.chunks.length === 0) return;
    if (restoredRef.current === activeBookId) return;

    const prog = useAsk.getState().bookProgress[activeBookId];
    if (prog && prog.chunkId && prog.chunkId !== payload.chunks[0].chunk_id) {
      const timer = setTimeout(() => {
        const el = document.querySelector(`[data-chunk-id="${CSS.escape(prog.chunkId)}"]`);
        if (el) {
          const topOffset = 72;
          const targetY = Math.max(0, window.scrollY + el.getBoundingClientRect().top - topOffset);
          window.scrollTo({ top: targetY, behavior: "instant" });
          restoredRef.current = activeBookId;
        }
      }, 100);
      return () => clearTimeout(timer);
    } else {
      restoredRef.current = activeBookId;
    }
  }, [payload, activeBookId]);

  // Track scroll position, active chapter, active chunk, and progress
  useEffect(() => {
    if (!payload || payload.chunks.length === 0) return;

    let raf = 0;
    const measure = () => {
      raf = 0;
      const scrollY = window.scrollY;
      const docHeight =
        document.documentElement.scrollHeight - window.innerHeight;
      const progress = docHeight > 0 ? Math.max(0, Math.min(1, scrollY / docHeight)) : 0;
      setScrollProgress(progress);
      setViewportRatio(
        document.documentElement.scrollHeight > 0
          ? window.innerHeight / document.documentElement.scrollHeight
          : 0.2
      );

      const threshold = window.innerHeight * 0.32;
      const chunks = payload.chunks;
      let currentChunk: Chunk | undefined;

      const x = window.innerWidth / 2;
      const hit = document.elementFromPoint(x, threshold)?.closest<HTMLElement>("[data-chunk-id]");
      if (hit) {
        const id = hit.getAttribute("data-chunk-id");
        if (id) currentChunk = chunkMap.get(id);
      }

      if (!currentChunk) {
        const approxIdx = Math.min(chunks.length - 1, Math.max(0, Math.floor(progress * chunks.length)));
        const start = Math.max(0, approxIdx - 6);
        const end = Math.min(chunks.length, approxIdx + 7);
        for (let i = start; i < end; i++) {
          const chunk = chunks[i];
          const el = document.querySelector(`[data-chunk-id="${CSS.escape(chunk.chunk_id)}"]`);
          if (el) {
            const rect = el.getBoundingClientRect();
            if (rect.top <= threshold && rect.bottom >= threshold) {
              currentChunk = chunk;
              break;
            }
          }
        }
      }
      if (!currentChunk) currentChunk = chunks[0];

      if (currentChunk) {
        setActiveChunkId(currentChunk.chunk_id);
        setActiveChapter(currentChunk.chapter);
        setActiveHeading(currentChunk.heading);

        const saved = useAsk.getState().bookProgress[activeBookId];
        if (
          scrollY === 0 &&
          saved &&
          saved.chunkId &&
          saved.chunkId !== chunks[0].chunk_id &&
          restoredRef.current !== activeBookId
        ) {
          return;
        }

        updateBookProgress(activeBookId, {
          pct: progress,
          chapter: currentChunk.chapter,
          chunkId: currentChunk.chunk_id,
        });
      }
    };

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [payload, activeBookId, chunkMap, updateBookProgress]);

  // Keyboard navigation shortcuts: [ and ] cycle glosses, Escape clears
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, [contenteditable]")) return;

      if (e.key === "Escape") {
        if (useAsk.getState().activeGlossId) {
          setActiveGloss(null);
        }
        clearHighlight();
        return;
      }

      if (e.key === "[" || e.key === "]") {
        const list = useAsk.getState().glosses;
        if (!list || list.length === 0) return;
        e.preventDefault();
        const currentId = useAsk.getState().activeGlossId;
        const currentIndex = list.findIndex((g) => g.id === currentId);
        let nextIndex = 0;
        if (e.key === "]") {
          nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % list.length;
        } else {
          nextIndex =
            currentIndex < 0
              ? list.length - 1
              : (currentIndex - 1 + list.length) % list.length;
        }
        const next = list[nextIndex];
        setActiveGloss(next.id);
        const chunkEl = document.querySelector(
          `[data-chunk-id="${CSS.escape(next.chunkId)}"]`
        );
        if (chunkEl) {
          chunkEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [setActiveGloss, clearHighlight]);

  // Jump helpers for TopBar & Rail
  const scrollToChunk = useCallback((chunkId: string) => {
    const el = document.querySelector(
      `[data-chunk-id="${CSS.escape(chunkId)}"]`
    );
    if (el) {
      const topOffset = 72;
      const targetY = Math.max(0, window.scrollY + el.getBoundingClientRect().top - topOffset);
      animateScrollTo(targetY, 520);
    }
  }, []);

  const jumpToTop = useCallback(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const handleScrub = useCallback((ratio: number) => {
    const docHeight =
      document.documentElement.scrollHeight - window.innerHeight;
    if (docHeight > 0) {
      window.scrollTo({ top: ratio * docHeight, behavior: "instant" });
    }
  }, []);

  // Visible anchor chunk for Composer
  const getVisibleChunk = useCallback(() => {
    if (!payload || payload.chunks.length === 0) {
      return { chunkId: "ch01-001", chapter: "1", heading: "" };
    }
    if (typeof window === "undefined") {
      return {
        chunkId: payload.chunks[0].chunk_id,
        chapter: payload.chunks[0].chapter,
        heading: payload.chunks[0].heading ?? "",
      };
    }
    const threshold = window.innerHeight * 0.35;
    const hit = document.elementFromPoint(window.innerWidth / 2, threshold)?.closest<HTMLElement>("[data-chunk-id]");
    if (hit) {
      const id = hit.getAttribute("data-chunk-id");
      const c = id ? chunkMap.get(id) : undefined;
      if (c) {
        return {
          chunkId: c.chunk_id,
          chapter: c.chapter,
          heading: c.heading ?? "",
        };
      }
    }

    const active = chunkMap.get(activeChunkId) || payload.chunks[0];
    return {
      chunkId: active.chunk_id,
      chapter: active.chapter,
      heading: active.heading ?? "",
    };
  }, [payload, chunkMap, activeChunkId]);

  // Chapters list for TopBar
  const chapters = useMemo(() => {
    if (!payload) return [];
    const list: { chapter: string; heading: string; chunkId: string }[] = [];
    payload.chunks.forEach((chunk, i) => {
      if (i === 0 || chunk.chapter !== payload.chunks[i - 1]?.chapter) {
        list.push({
          chapter: chunk.chapter,
          heading: chunk.heading,
          chunkId: chunk.chunk_id,
        });
      }
    });
    return list;
  }, [payload]);

  const totalChapters = useMemo(() => {
    if (!payload) return 0;
    const set = new Set(payload.chunks.map((c) => c.chapter));
    return set.size;
  }, [payload]);

  const currentBook = booksCatalog.find((b) => b.book_id === activeBookId);
  const currentBookTitle = currentBook?.title || payload?.title || "Fundamentals of Data Engineering";

  return (
    <>
      <div className={`library-pane ${viewMode === "library" ? "is-active" : "is-hidden"}`}>
        <LibraryView />
      </div>

      <div className={`reader-pane ${viewMode === "reader" ? "is-active" : "is-hidden"}`}>
        <main
          className="reader"
          ref={readerRef}
          onPointerDown={(event) => {
            if (
              (event.target as HTMLElement).closest(
                "mark, .gloss-card, .lens, .gloss-sheet, .composer-dock, .topbar, button, .return-spot-banner"
              )
            ) {
              return;
            }
            clearHighlight();
          }}
        >
          {/* TopBar navigation */}
          <TopBar
            bookTitle={currentBookTitle}
            activeChapter={activeChapter}
            activeHeading={activeHeading}
            progress={scrollProgress}
            onJumpTop={jumpToTop}
            chapters={chapters}
            onJumpChunk={scrollToChunk}
          />

      {/* Return spot floating pill banner */}
      {returnSpot && (
        <aside className="return-spot-banner" role="status" aria-label="Return to reading position">
          <button
            type="button"
            className="return-spot-pill"
            onClick={() => {
              animateScrollTo(returnSpot.scrollY, 520);
              clearReturnSpot();
            }}
            title={`Back to ${returnSpot.label}`}
          >
            <span className="return-spot-arrow" aria-hidden="true">←</span>
            <span className="return-spot-label">Back to {returnSpot.label}</span>
          </button>
          <button
            type="button"
            className="return-spot-close"
            onClick={() => clearReturnSpot()}
            title="Dismiss return button"
            aria-label="Dismiss return button"
          >
            ×
          </button>
        </aside>
      )}

      {/* Reader Grid */}
      <div className="reader-grid">
        {/* Left Column: Progress Minimap Rail */}
        <div className="rg-rail">
          <div className="rail-sticky">
            {payload ? (
              <Rail
                chunks={payload.chunks}
                activeChunkId={activeChunkId}
                scrollProgress={scrollProgress}
                viewportRatio={viewportRatio}
                onScrub={handleScrub}
              />
            ) : null}
          </div>
        </div>

        {/* Center Column: Prose */}
        <div className="rg-prose" ref={textRef}>
          {loadError ? <p className="meta load-error">{loadError}</p> : null}
          {!loadError && !payload ? (
            <p className="meta prose-loading">
              Loading the book…
            </p>
          ) : null}

          {payload ? (
            <>
              {/* Book Header */}
              <header className="book-header">
                <h1 className="book-title">
                  {payload.title || "Fundamentals of Data Engineering"}
                </h1>
                <p className="book-subtitle">
                  {payload.author || "Joe Reis & Matt Housley"} · {totalChapters} Chapters
                </p>
              </header>

              {/* Chunks */}
              <div className="prose-chunks">
                {payload.chunks.map((chunk, index) => {
                  const isChapterStart =
                    index === 0 ||
                    chunk.chapter !== payload.chunks[index - 1]?.chapter;
                  const showHeading =
                    Boolean(chunk.heading) &&
                    chunk.heading !== payload.chunks[index - 1]?.heading;
                  const focus = highlight?.chunkId === chunk.chunk_id;

                  return (
                    <ChunkBlock
                      key={chunk.chunk_id}
                      chunk={chunk}
                      isChapterStart={isChapterStart}
                      showHeading={showHeading}
                      focus={focus}
                      quote={focus ? highlight?.quote ?? "" : ""}
                      at={focus ? highlight?.at : undefined}
                      highlightNonce={focus ? highlight?.nonce : undefined}
                    />
                  );
                })}
              </div>
            </>
          ) : null}
        </div>

        {/* Right Column: Margin Physics & Cards */}
        <div className="rg-margin">
          <Margin proseRef={textRef} wide={wide} />
        </div>
      </div>

      {/* Floating Selection Lens */}
      <Lens payload={payload} containerRef={readerRef} />

      {/* Whole-book Ask Composer */}
      <Composer getAnchorChunk={getVisibleChunk} chunks={payload?.chunks} />
    </main>
  </div>
</>
  );
}

function renderSegment(
  seg: Segment,
  key: string | number,
  onSelectGloss: (id: string) => void,
  highlightNonce?: number
) {
  let content: React.ReactNode = seg.text;

  if (seg.isActiveMark) {
    content = (
      <mark className="cite-mark" key={`mark-${key}-${highlightNonce || 0}`}>
        {content}
      </mark>
    );
  }

  if (seg.isGlossAnchor && seg.glossId) {
    const gid = seg.glossId;
    content = (
      <span
        key={`gloss-${key}`}
        className={`gloss-anchor ${seg.isActiveGloss ? "is-active" : ""}`}
        data-gloss-id={gid}
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          onSelectGloss(gid);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            onSelectGloss(gid);
          }
        }}
      >
        {content}
      </span>
    );
  }

  if (seg.highlightColor) {
    content = (
      <span
        key={`hl-${key}`}
        className="hl-mark"
        data-color={seg.highlightColor}
        data-hl-id={seg.highlightId}
      >
        {content}
      </span>
    );
  }

  return <span key={key}>{content}</span>;
}

const ChunkBlock = memo(function ChunkBlock({
  chunk,
  isChapterStart,
  showHeading,
  focus,
  quote,
  at,
  highlightNonce,
}: {
  chunk: Chunk;
  isChapterStart: boolean;
  showHeading: boolean;
  focus: boolean;
  quote: string;
  at?: number;
  highlightNonce?: number;
}) {
  const highlights = useAsk((s) => s.highlightsByChunk[chunk.chunk_id] ?? EMPTY_ARRAY);
  const chunkGlosses = useAsk((s) => s.glossAnchorsByChunk[chunk.chunk_id] ?? EMPTY_ARRAY);
  const activeGlossId = useAsk((s) => {
    const activeId = s.activeGlossId;
    if (!activeId) return null;
    const glosses = s.glossAnchorsByChunk[chunk.chunk_id];
    if (!glosses || glosses.length === 0) return null;
    return glosses.some((g) => g.id === activeId) ? activeId : null;
  });
  const setActiveGloss = useAsk((s) => s.setActiveGloss);

  const paragraphs = useMemo(() => paragraphList(chunk.text), [chunk.text]);
  const joinedText = useMemo(() => paragraphs.join("\n"), [paragraphs]);
  const ref = useRef<HTMLElement | null>(null);

  // Separate body vs heading highlights and glosses
  const bodyHighlights = useMemo(
    () => highlights.filter((h) => !isHeadingOffset(h.start)),
    [highlights]
  );
  const headingHighlights = useMemo(
    () => highlights.filter((h) => isHeadingOffset(h.start)),
    [highlights]
  );

  const bodyGlosses = useMemo(
    () => chunkGlosses.filter((g) => !isHeadingOffset(g.at)),
    [chunkGlosses]
  );
  const headingGlosses = useMemo(
    () => chunkGlosses.filter((g) => isHeadingOffset(g.at)),
    [chunkGlosses]
  );

  // Smooth ease-out citation jump with content-visibility late-paint correction
  useEffect(() => {
    if (!focus) return;
    const section = ref.current;
    if (!section) return;

    const target = () =>
      section.querySelector("mark.cite-mark") ??
      section.querySelector(".gloss-anchor.is-active") ??
      section;

    const scrollBox = section.closest(".reader");
    const visible = (element: Element) => {
      const rect = element.getBoundingClientRect();
      let view = { top: 0, bottom: window.innerHeight };
      if (scrollBox) {
        const style = getComputedStyle(scrollBox);
        if (style.overflowY === "auto" || style.overflowY === "scroll") {
          const box = scrollBox.getBoundingClientRect();
          view = { top: box.top, bottom: box.bottom };
        }
      }
      return rect.top >= view.top && rect.bottom <= view.bottom;
    };

    if (visible(target()) && !highlightNonce) return;
    const box = scrollingBox(section);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      box.scrollTop += centerDelta(target(), box);
      return;
    }

    const from = box.scrollTop;
    const distance = centerDelta(target(), box);
    const started = performance.now();
    const ms = 520;
    let frame = 0;

    const ease = (t: number) =>
      t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

    const step = (now: number) => {
      const t = Math.min(1, (now - started) / ms);
      box.scrollTop = from + distance * ease(t);
      if (t < 1) {
        frame = requestAnimationFrame(step);
        return;
      }
      // Content-visibility late estimation correction
      const left = centerDelta(target(), box);
      if (Math.abs(left) > 24) box.scrollTop += left;
    };

    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [focus, quote, at, highlightNonce]);

  // Compute heading segments using splitParagraphSegments
  const renderedHeading = useMemo(() => {
    const hText = chunk.heading ?? "";
    if (!hText) return null;

    const mappedHighlights = headingHighlights.map((h) => {
      const s = decodeHeadingOffset(h.start);
      const e = decodeHeadingOffset(h.end);
      return {
        ...h,
        start: Math.min(s, e),
        end: Math.max(s, e),
      };
    });

    const headingGlossRanges = headingGlosses
      .map((g) => {
        if (!g.quote) return null;
        const decodedAt =
          g.at !== undefined && isHeadingOffset(g.at)
            ? decodeHeadingOffset(g.at)
            : undefined;
        const span = findQuoteSpan(hText, g.quote, decodedAt);
        if (!span) return null;
        return {
          id: g.id,
          start: span[0],
          end: span[1],
          active: g.id === activeGlossId,
        };
      })
      .filter(
        (
          v
        ): v is {
          id: string;
          start: number;
          end: number;
          active: boolean;
        } => v !== null
      );

    let citationRange: [number, number] | null = null;
    if (focus && quote) {
      const decodedAt =
        at != null && isHeadingOffset(at)
          ? decodeHeadingOffset(at)
          : undefined;
      const span = findQuoteSpan(hText, quote, decodedAt);
      if (span) {
        citationRange = [span[0], span[1]];
      }
    }

    const segs = splitParagraphSegments(hText, 0, {
      highlights: mappedHighlights,
      glossRanges: headingGlossRanges,
      citationRange,
    });

    if (segs.length === 0) return hText;

    return segs.map((seg, sIdx) =>
      renderSegment(seg, `h-${sIdx}`, setActiveGloss, highlightNonce)
    );
  }, [
    chunk.heading,
    headingHighlights,
    headingGlosses,
    activeGlossId,
    focus,
    quote,
    at,
    setActiveGloss,
    highlightNonce,
  ]);

  // Compute paragraph segments using splitParagraphSegments with fallback to markQuote
  const renderedParagraphs = useMemo(() => {
    try {
      const glossRanges = bodyGlosses
        .map((g) => {
          if (!g.quote) return null;
          let span: [number, number] | null = null;
          if (g.chunkId === chunk.chunk_id && !g.endChunkId) {
            span = findQuoteSpan(joinedText, g.quote, g.at);
          } else if (g.chunkId === chunk.chunk_id && g.endChunkId) {
            span = findQuoteSpanForRole(joinedText, g.quote, "start", g.at);
          } else if (g.endChunkId === chunk.chunk_id) {
            span = findQuoteSpanForRole(joinedText, g.quote, "end");
          }
          if (!span) return null;
          return {
            id: g.id,
            start: span[0],
            end: span[1],
            active: g.id === activeGlossId,
          };
        })
        .filter(
          (
            v
          ): v is {
            id: string;
            start: number;
            end: number;
            active: boolean;
          } => v !== null
        );

      let citationRange: [number, number] | null = null;
      if (focus && quote) {
        const cHit = findQuoteSpan(
          joinedText,
          quote,
          isHeadingOffset(at) ? undefined : at
        );
        if (cHit) {
          citationRange = [cHit[0], cHit[1]];
        }
      }

      let running = 0;
      return paragraphs.map((pText, pIdx) => {
        const segs = splitParagraphSegments(pText, running, {
          highlights: bodyHighlights,
          glossRanges,
          citationRange,
        });
        running += pText.length + 1;

        return (
          <p key={pIdx} className="chunk-p">
            {segs.map((seg, sIdx) =>
              renderSegment(
                seg,
                `${pIdx}-${sIdx}`,
                setActiveGloss,
                highlightNonce
              )
            )}
          </p>
        );
      });
    } catch {
      // Fallback to markQuote
      const { parts } = markQuote(paragraphs, quote, at);
      return parts.map((part, index) => (
        <p key={index} className="chunk-p">
          {part.mark ? (
            <>
              {part.text.slice(0, part.mark[0])}
              <mark className="cite-mark" key={`cite-${highlightNonce || 0}`}>
                {part.text.slice(part.mark[0], part.mark[1])}
              </mark>
              {part.text.slice(part.mark[1])}
            </>
          ) : (
            part.text
          )}
        </p>
      ));
    }
  }, [
    joinedText,
    chunk.chunk_id,
    paragraphs,
    bodyHighlights,
    bodyGlosses,
    activeGlossId,
    focus,
    quote,
    at,
    setActiveGloss,
    highlightNonce,
  ]);

  const engine = engineUrl();

  return (
    <section
      className={`chunk ${isChapterStart ? "is-chapter-start" : ""}`}
      data-chunk-id={chunk.chunk_id}
      data-chapter={chunk.chapter}
      data-heading={chunk.heading}
      ref={ref}
    >
      {showHeading && chunk.heading ? (
        <h2 className="chunk-heading">
          {renderedHeading}
        </h2>
      ) : null}

      <div className="chunk-paragraphs">
        {renderedParagraphs}
      </div>

      {chunk.figures.map((figure) => (
        <figure key={figure.id} className="chunk-figure">
          <img
            src={`${engine}${figure.src}`}
            alt={figure.caption || figure.id}
            width={figure.width}
            height={figure.height}
            loading="lazy"
            decoding="async"
            className="chunk-img"
          />
          {figure.caption ? (
            <figcaption className="chunk-caption">
              {figure.caption}
            </figcaption>
          ) : null}
        </figure>
      ))}
    </section>
  );
});
