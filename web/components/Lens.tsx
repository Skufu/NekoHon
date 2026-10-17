"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import type { ChunksPayload } from "@/lib/engine";
import {
  formatChapter,
  isHeadingOffset,
  offsetInChunk,
  resolveSelection,
  type HighlightSpan,
  type MarkerColor,
} from "@/lib/anchor";
import { useAsk } from "@/lib/store";

export type Marker = "yellow" | "green" | "blue" | "pink";

export const MARKERS: { key: Marker; label: string; color: string }[] = [
  { key: "yellow", label: "Yellow", color: "var(--mk-yellow)" },
  { key: "green", label: "Green", color: "var(--mk-green)" },
  { key: "blue", label: "Blue", color: "var(--mk-blue)" },
  { key: "pink", label: "Pink", color: "var(--mk-pink)" },
];

type LensState = {
  chunkId: string;
  endChunkId?: string;
  chapter: string;
  heading: string;
  quote: string;
  start: number;
  end: number;
  spans: HighlightSpan[];
  mode: "actions" | "ask";
};

type Position = {
  x: number;
  y: number;
  below: boolean;
  arrow: number;
  docked: boolean;
};

export default function Lens({
  payload,
  containerRef,
  rootEl,
}: {
  payload?: ChunksPayload | null;
  containerRef?: RefObject<HTMLElement | null>;
  rootEl?: HTMLElement | null;
}) {
  const marker = useAsk((s) => s.marker ?? "yellow") as Marker;
  const setMarker = useAsk((s) => s.setMarker);
  const addHighlight = useAsk((s) => s.addHighlight);
  const askSelection = useAsk((s) => s.askSelection);

  const [lens, setLens] = useState<LensState | null>(null);
  const [pos, setPos] = useState<Position | null>(null);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const lensRef = useRef<LensState | null>(null);
  lensRef.current = lens;
  const rangeRef = useRef<Range | null>(null);
  const draggingRef = useRef(false);

  const close = useCallback((clearSelection = true) => {
    setLens(null);
    setPos(null);
    setDraft("");
    rangeRef.current = null;
    if (clearSelection) {
      window.getSelection()?.removeAllRanges();
    }
  }, []);

  const getContainer = useCallback(() => {
    return containerRef?.current || rootEl || (typeof document !== "undefined" ? document.body : null);
  }, [containerRef, rootEl]);

  // Position calculation
  const place = useCallback(() => {
    const l = lensRef.current;
    const box = boxRef.current;
    const range = rangeRef.current;
    if (!l || !range) return;

    const rects = Array.from(range.getClientRects()).filter(
      (r) => r.width > 0 && r.height > 0
    );
    if (!rects.length) return;

    const first = rects[0];
    const lastR = rects[rects.length - 1];
    const vw = window.innerWidth;
    const w = box?.offsetWidth || (l.mode === "ask" ? 360 : 220);
    const h = box?.offsetHeight || 38;

    const coarse = window.matchMedia("(pointer: coarse)").matches;
    if (coarse) {
      const x = Math.max(12, (vw - w) / 2);
      const y = window.innerHeight - h - 16;
      setPos({ x, y, below: false, arrow: w / 2, docked: true });
      return;
    }

    let below = first.top - h - 12 < 68;
    let y = below ? lastR.bottom + 12 : first.top - h - 12;
    if (below && y + h > window.innerHeight - 8) {
      below = false;
      y = Math.max(68, first.top - h - 12);
    }

    const centerX =
      rects.length > 1
        ? (Math.min(...rects.map((r) => r.left)) +
            Math.max(...rects.map((r) => r.right))) /
          2
        : (first.left + first.right) / 2;

    const x = Math.max(12, Math.min(vw - w - 12, centerX - w / 2));
    const arrowAt = below ? (lastR.left + lastR.right) / 2 : centerX;
    const arrow = Math.max(16, Math.min(w - 16, arrowAt - x));

    setPos({ x, y, below, arrow, docked: false });
  }, []);

  useLayoutEffect(() => {
    if (!lens) return;
    place();
    const ro = new ResizeObserver(() => place());
    if (boxRef.current) ro.observe(boxRef.current);
    const onScrollOrResize = () => requestAnimationFrame(place);
    window.addEventListener("scroll", onScrollOrResize, { passive: true });
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", onScrollOrResize);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [lens, place]);

  // Selection inspection
  useEffect(() => {
    const container = getContainer();
    if (!container) return;

    let timer: ReturnType<typeof setTimeout> | null = null;

    const evaluate = () => {
      if (lensRef.current?.mode === "ask") return;
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        if (lensRef.current?.mode === "actions") {
          close(false);
        }
        return;
      }

      const range = sel.getRangeAt(0);
      const text = sel.toString().trim();
      if (!text) {
        if (lensRef.current?.mode === "actions") {
          close(false);
        }
        return;
      }

      const resolved = resolveSelection(container, range);
      if (!resolved) {
        if (lensRef.current?.mode === "actions") {
          close(false);
        }
        return;
      }

      const chunkId = resolved.startChunkId;
      let chapter = resolved.chapter;
      if (!chapter && payload) {
        chapter =
          payload.chunks.find((c) => c.chunk_id === chunkId)?.chapter ?? "";
      }
      if (!chapter) {
        const m = chunkId.match(/^ch0*(\d+)/);
        if (m) chapter = m[1];
      }

      let heading = resolved.heading;
      if (!heading && payload) {
        heading =
          payload.chunks.find((c) => c.chunk_id === chunkId)?.heading ?? "";
      }

      rangeRef.current = range.cloneRange();
      setLens({
        chunkId,
        endChunkId: resolved.endChunkId,
        chapter,
        heading,
        quote: resolved.quote,
        start: resolved.start,
        end: resolved.end,
        spans: resolved.spans,
        mode: "actions",
      });
    };

    const onPointerDown = (e: PointerEvent) => {
      if (boxRef.current?.contains(e.target as Node)) return;
      draggingRef.current = container.contains(e.target as Node);
      if (lensRef.current?.mode === "ask") {
        close(false);
      }
    };

    const onPointerUp = () => {
      const sel = window.getSelection();
      const anchorEl =
        sel?.anchorNode instanceof Element
          ? sel.anchorNode
          : sel?.anchorNode?.parentElement;
      const focusEl =
        sel?.focusNode instanceof Element
          ? sel.focusNode
          : sel?.focusNode?.parentElement;
      const insideContainer = Boolean(
        (anchorEl && container.contains(anchorEl)) ||
          (focusEl && container.contains(focusEl))
      );
      const hasNonCollapsed = Boolean(
        sel && !sel.isCollapsed && sel.rangeCount > 0 && insideContainer
      );

      if (!draggingRef.current && !hasNonCollapsed) return;
      draggingRef.current = false;
      if (timer) clearTimeout(timer);
      timer = setTimeout(evaluate, 10);
    };

    const onSelectionChange = () => {
      if (draggingRef.current) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(evaluate, 140);
    };

    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("pointerup", onPointerUp, true);
    document.addEventListener("selectionchange", onSelectionChange);

    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("pointerup", onPointerUp, true);
      document.removeEventListener("selectionchange", onSelectionChange);
      if (timer) clearTimeout(timer);
    };
  }, [getContainer, payload, close]);

  // Mode transition helpers
  const toAsk = useCallback((initial = "") => {
    const l = lensRef.current;
    if (!l) return;
    setDraft(initial);
    setLens({ ...l, mode: "ask" });
    window.getSelection()?.removeAllRanges();
  }, []);

  // Autofocus input when entering ask mode
  useLayoutEffect(() => {
    if (lens?.mode === "ask" && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.setSelectionRange(draft.length, draft.length);
    }
  }, [lens?.mode, draft.length]);

  // Instant Type-to-Ask keyboard capture
  useEffect(() => {
    if (!lens || lens.mode !== "actions") return;

    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tgt = e.target as HTMLElement;
      if (tgt.closest("input, textarea, [contenteditable]")) return;

      if (e.key === "Escape") {
        e.preventDefault();
        close();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        toAsk("");
        return;
      }
      if (e.key.length === 1 && e.key !== " ") {
        e.preventDefault();
        e.stopPropagation();
        toAsk(e.key);
      }
    };

    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [lens, close, toAsk]);

  if (!lens) return null;

  const onPickHighlight = (color: Marker) => {
    if (lens.spans.length > 0) {
      for (const span of lens.spans) {
        if (span.start >= 0 || isHeadingOffset(span.start)) {
          addHighlight({
            chunkId: span.chunkId,
            chapter: span.chapter,
            start: span.start,
            end: span.end,
            quote: span.quote,
            color: color as MarkerColor,
          });
        }
      }
      setMarker(color as MarkerColor);
    } else if (lens.start >= 0 || isHeadingOffset(lens.start)) {
      addHighlight({
        chunkId: lens.chunkId,
        chapter: lens.chapter,
        start: lens.start,
        end: lens.end,
        quote: lens.quote,
        color: color as MarkerColor,
      });
      setMarker(color as MarkerColor);
    }
    close();
  };

  const onExplain = () => {
    askSelection(
      "",
      lens.quote,
      lens.chunkId,
      lens.chapter,
      lens.heading,
      lens.start,
      lens.endChunkId
    );
    close();
  };

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(
        `"${lens.quote}" (${formatChapter(lens.chapter)})`
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Ignore clipboard error
    }
  };

  const onSubmitAsk = (e: React.FormEvent) => {
    e.preventDefault();
    const q = draft.trim();
    if (!q) return;
    askSelection(
      q,
      lens.quote,
      lens.chunkId,
      lens.chapter,
      lens.heading,
      lens.start,
      lens.endChunkId
    );
    close();
  };

  const activeColor = MARKERS.find((m) => m.key === marker)?.color ?? "var(--mk-yellow)";

  return (
    <div
      ref={boxRef}
      role={lens.mode === "actions" ? "toolbar" : "dialog"}
      aria-label={
        lens.mode === "ask" ? "Ask about selection" : "Selection actions"
      }
      className={`lens${lens.mode === "ask" ? " lens-morph" : ""}`}
      style={{
        left: pos?.x ?? -9999,
        top: pos?.y ?? -9999,
        visibility: pos ? "visible" : "hidden",
      }}
      onMouseDown={(e) => {
        const tag = (e.target as HTMLElement).tagName;
        if (tag !== "INPUT" && tag !== "TEXTAREA") e.preventDefault();
      }}
    >
      {/* Arrow pointer */}
      {pos && !pos.docked && (
        <span
          className={`lens-arrow ${pos.below ? "is-below" : "is-above"}`}
          style={{ left: pos.arrow }}
          aria-hidden
        />
      )}

      {lens.mode === "actions" ? (
        <div className="lens-actions">
          {/* Explain button */}
          <button
            type="button"
            onClick={onExplain}
            className="lens-btn"
          >
            Explain
          </button>

          {/* Ask button */}
          <button
            type="button"
            onClick={() => toAsk("")}
            className="lens-btn"
          >
            Ask
            <span className="lens-caret" aria-hidden />
          </button>

          {/* Copy button */}
          <button
            type="button"
            onClick={onCopy}
            className="lens-btn"
          >
            {copied ? "Copied" : "Copy"}
          </button>

          {(lens.spans.length > 0 || lens.start >= 0 || isHeadingOffset(lens.start)) && (
            <>
              <span className="lens-sep" aria-hidden />

              {/* Highlighter Swatch Group */}
              <div className="lens-hl-group">
                <button
                  type="button"
                  onClick={() => onPickHighlight(marker)}
                  aria-label={`Highlight with ${marker}`}
                  className="lens-hl-trigger"
                >
                  <span
                    className="lens-dot"
                    style={{ background: activeColor }}
                    aria-hidden
                  />
                </button>
                <div className="lens-hl-drawer">
                  <div className="lens-hl-row">
                    {MARKERS.map((m) => (
                      <button
                        key={m.key}
                        type="button"
                        aria-label={`${m.label} highlight`}
                        onClick={() => onPickHighlight(m.key)}
                        className={`lens-dot ${
                          m.key === marker ? "is-active" : ""
                        }`}
                        style={{ background: m.color }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      ) : (
        /* Ask mode form */
        <form
          onSubmit={onSubmitAsk}
          className="lens-form"
        >
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                setLens((prev) => (prev ? { ...prev, mode: "actions" } : null));
              }
            }}
            placeholder="Ask about the highlighted word…"
            className="lens-input"
          />
          <button
            type="submit"
            disabled={!draft.trim()}
            aria-label="Submit question"
            className="lens-submit"
          >
            ↑
          </button>
        </form>
      )}
    </div>
  );
}
