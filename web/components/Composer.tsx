"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { Chunk } from "@/lib/engine";
import { useAsk } from "@/lib/store";

export type ComposerProps = {
  getAnchorChunk: () => { chunkId: string; chapter: string; heading?: string };
  chunks?: Chunk[];
};

const BASE_SUGGESTIONS = [
  "What is a watermark?",
  "What does CRUD stand for?",
  "What are the stages of the data engineering lifecycle?",
];

const VALID_QUESTION_PREFIX = /^(?:What|How|Why|When|Where|Which|Who)\s/;

function extractQuestions(
  chunks: Chunk[] | undefined,
  activeChunkId: string,
  activeChapter: string
): string[] {
  if (!chunks || chunks.length === 0) return [];
  const matched: string[] = [];
  const seen = new Set<string>();

  const activeChunk = chunks.find((c) => c.chunk_id === activeChunkId);
  const chapterChunks = chunks.filter(
    (c) => c.chapter === activeChapter && c.chunk_id !== activeChunkId
  );
  const prioritized = activeChunk
    ? [activeChunk, ...chapterChunks]
    : chapterChunks;

  for (const c of prioritized) {
    const sentences = c.text.match(/([A-Z][^.?!;\n]{10,100}\?)/g);
    if (sentences) {
      for (const s of sentences) {
        const clean = s.trim().replace(/\s+/g, " ");
        if (
          clean.length >= 18 &&
          clean.length <= 62 &&
          VALID_QUESTION_PREFIX.test(clean) &&
          !seen.has(clean.toLowerCase())
        ) {
          seen.add(clean.toLowerCase());
          matched.push(clean);
          if (matched.length >= 3) {
            return matched.slice(0, 3);
          }
        }
      }
    }
  }
  return matched.slice(0, 3);
}

export default function Composer({ getAnchorChunk, chunks }: ComposerProps) {
  const mode = useAsk((s) => s.mode);
  const setMode = useAsk((s) => s.setMode);
  const submitWholeBook = useAsk((s) => s.submitWholeBook);
  const startQuiz = useAsk((s) => s.startQuiz);
  const engineReady = useAsk((s) => s.engineReady);
  const glosses = useAsk((s) => s.glosses);
  const activeGlossId = useAsk((s) => s.activeGlossId);
  const setActiveGloss = useAsk((s) => s.setActiveGloss);
  const toggleMinimizeGloss = useAsk((s) => s.toggleMinimizeGloss);

  const [isWide, setIsWide] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [draft, setDraft] = useState("");

  const wrapRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const moreBtnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const item0Ref = useRef<HTMLButtonElement>(null);
  const item1Ref = useRef<HTMLButtonElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track viewport width (>= 1080px is wide, < 1080px is narrow)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(min-width: 1080px)");
    const update = () => setIsWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Compute interplay with glosses on mobile/narrow viewports
  const activeGloss = glosses.find((g) => g.id === activeGlossId) ?? null;
  const hidden = !isWide && Boolean(activeGloss && !activeGloss.minimized);
  const parkedGloss =
    !isWide && !hidden
      ? (activeGloss && activeGloss.minimized
          ? activeGloss
          : glosses.find((g) => g.minimized) ?? null)
      : null;
  const parked = Boolean(parkedGloss);

  const handleRestore = () => {
    if (!parkedGloss) return;
    if (parkedGloss.minimized) {
      toggleMinimizeGloss(parkedGloss.id);
    }
    setActiveGloss(parkedGloss.id);
  };

  const hiddenRef = useRef(hidden);
  hiddenRef.current = hidden;

  const isRevealed = Boolean(isOpen || draft.trim().length > 0 || isMenuOpen);

  const openPill = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsOpen(true);
  }, []);

  const openAndFocus = useCallback(() => {
    openPill();
    requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
    });
  }, [openPill]);

  const closePill = useCallback(() => {
    setIsMenuOpen(false);
    setIsOpen(false);
    inputRef.current?.blur();
    moreBtnRef.current?.blur();
  }, []);

  // Global shortcuts: "/" (when not typing in an input) and Cmd/Ctrl+K
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable]")) return;

      if (
        e.key === "/" ||
        ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k")
      ) {
        e.preventDefault();
        openAndFocus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openAndFocus]);

  // Click outside to close overflow popover menu
  useEffect(() => {
    if (!isMenuOpen) return;
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        menuRef.current &&
        !menuRef.current.contains(target) &&
        !moreBtnRef.current?.contains(target)
      ) {
        setIsMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [isMenuOpen]);

  // Focus first menu item when menu opens
  useEffect(() => {
    if (isMenuOpen) {
      const timer = setTimeout(() => {
        item0Ref.current?.focus();
      }, 40);
      return () => clearTimeout(timer);
    }
  }, [isMenuOpen]);

  // Stop health polling and timer on unmount
  useEffect(() => {
    return () => {
      useAsk.getState().stopHealthPolling?.();
      if (closeTimerRef.current) {
        clearTimeout(closeTimerRef.current);
      }
    };
  }, []);

  const anchor = getAnchorChunk();
  const dynamicQuestions = useMemo(() => {
    return extractQuestions(chunks, anchor.chunkId, anchor.chapter);
  }, [chunks, anchor.chunkId, anchor.chapter]);

  const allSuggestions = useMemo(() => {
    const combined = [...dynamicQuestions, ...BASE_SUGGESTIONS];
    const seen = new Set<string>();
    const dedupe: string[] = [];
    for (const s of combined) {
      const lower = s.toLowerCase();
      if (!seen.has(lower)) {
        seen.add(lower);
        dedupe.push(s);
      }
    }
    return dedupe;
  }, [dynamicQuestions]);

  const activeSuggestions = useMemo(() => {
    const q = draft.trim().toLowerCase();
    if (!q) {
      return allSuggestions.slice(0, 3);
    }
    const filtered = allSuggestions.filter((s) => s.toLowerCase().includes(q));
    filtered.sort((a, b) => {
      const aStarts = a.toLowerCase().startsWith(q) ? 0 : 1;
      const bStarts = b.toLowerCase().startsWith(q) ? 0 : 1;
      return aStarts - bStarts;
    });
    return filtered.slice(0, 3);
  }, [draft, allSuggestions]);

  const handleAsk = (questionText: string) => {
    const text = questionText.trim();
    if (!text || !engineReady) return;
    const currentAnchor = getAnchorChunk();
    submitWholeBook(
      currentAnchor.chunkId,
      currentAnchor.chapter,
      text,
      currentAnchor.heading || ""
    );
    setDraft("");
    closePill();
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    handleAsk(draft);
  };

  const handleQuiz = () => {
    if (!engineReady) return;
    const currentAnchor = getAnchorChunk();
    startQuiz(currentAnchor.chunkId, currentAnchor.chapter);
    setDraft("");
    closePill();
  };

  // Keyboard navigation within the overflow menu
  const handleMenuKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      setIsMenuOpen(false);
      moreBtnRef.current?.focus();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      item1Ref.current?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      item0Ref.current?.focus();
    }
  };

  // Keyboard handler on container: Esc closes menu first, then closes pill
  const handleContainerKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (isMenuOpen) {
        setIsMenuOpen(false);
        moreBtnRef.current?.focus();
      } else {
        closePill();
      }
    }
  };

  // Hover handlers on wrapper
  const handleMouseEnter = () => {
    if (parked || hidden) return;
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsOpen(true);
  };

  const handleMouseLeave = () => {
    if (
      document.activeElement === inputRef.current ||
      draft.trim().length > 0 ||
      isMenuOpen
    ) {
      return;
    }
    closeTimerRef.current = setTimeout(() => {
      if (
        document.activeElement !== inputRef.current &&
        draft.trim().length === 0 &&
        !isMenuOpen
      ) {
        setIsOpen(false);
      }
    }, 180);
  };

  // Blur on container: close on blur-with-empty-draft
  const handleContainerBlur = (e: React.FocusEvent) => {
    if (containerRef.current?.contains(e.relatedTarget as Node)) {
      return;
    }
    if (draft.trim().length === 0 && !isMenuOpen) {
      closeTimerRef.current = setTimeout(() => {
        setIsOpen(false);
      }, 150);
    }
  };

  return (
    <div
      ref={wrapRef}
      className={`composer-dock ${isRevealed ? "is-open" : ""} ${hidden ? "is-hidden" : ""} ${parked ? "is-parked" : ""}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onKeyDown={handleContainerKeyDown}
    >
      {/* Suggestions stack */}
      {isRevealed && !isMenuOpen && activeSuggestions.length > 0 && (
        <div
          className="composer-suggestions"
          role="group"
          aria-label="Suggested questions"
        >
          {activeSuggestions.map((s) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleAsk(s)}
              className="composer-suggestion-pill"
              title={s}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Overflow menu popover */}
      {isRevealed && isMenuOpen && (
        <div
          ref={menuRef}
          className="composer-menu"
          role="menu"
          aria-label="Composer options"
          onKeyDown={handleMenuKeyDown}
        >
          <button
            ref={item0Ref}
            type="button"
            role="menuitem"
            className="composer-menu-item"
            onClick={() => setMode(mode === "answer" ? "ask" : "answer")}
          >
            <span className="composer-menu-label">
              Mode: {mode === "answer" ? "Answer" : "Quote first"}
            </span>
          </button>
          <button
            ref={item1Ref}
            type="button"
            role="menuitem"
            className="composer-menu-item"
            onClick={handleQuiz}
            disabled={!engineReady}
          >
            <span className="composer-menu-label">Quiz this passage</span>
          </button>
        </div>
      )}

      {/* Morphing container */}
      <div
        ref={containerRef}
        className={`composer-orb-shell ${isRevealed ? "is-open" : ""}`}
        onBlur={handleContainerBlur}
      >
        {/* Collapsed trigger button */}
        <button
          type="button"
          className="composer-orb-trigger"
          onClick={parked ? handleRestore : openAndFocus}
          aria-label={
            parked ? "Restore answer note" : "Ask the whole book (press /)"
          }
          title={
            parked ? "Restore answer note" : "Ask whole book (/ to focus)"
          }
          tabIndex={isRevealed ? -1 : 0}
          aria-hidden={isRevealed}
        >
          {parked ? (
            <svg
              className="composer-orb-glyph"
              width="18"
              height="18"
              viewBox="0 0 18 18"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M4.5 11.5L9 7l4.5 4.5"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          ) : (
            <span className="composer-orb-glyph">/</span>
          )}
        </button>

        {/* Expanded form */}
        <form
          onSubmit={handleSubmit}
          className="composer-form"
          aria-hidden={!isRevealed}
        >
          {/* Overflow button */}
          <button
            ref={moreBtnRef}
            type="button"
            className="composer-more-btn"
            onClick={() => setIsMenuOpen((v) => !v)}
            aria-label="More options"
            aria-haspopup="menu"
            aria-expanded={isMenuOpen}
            tabIndex={isRevealed ? 0 : -1}
          >
            <span className="composer-more-dots" aria-hidden="true">
              ⋯
            </span>
          </button>

          {/* Input */}
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              engineReady ? "Ask about the whole book… (/)" : "Warming up…"
            }
            disabled={!engineReady}
            aria-label="Ask about the whole book"
            className="composer-input"
            tabIndex={isRevealed ? 0 : -1}
          />

          {/* Submit button */}
          <button
            type="submit"
            disabled={!engineReady || !draft.trim()}
            aria-label="Submit question"
            className="composer-submit"
            tabIndex={isRevealed ? 0 : -1}
          >
            <svg
              className="composer-submit-icon"
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M8 12.5V3.5M8 3.5L4 7.5M8 3.5L12 7.5"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
