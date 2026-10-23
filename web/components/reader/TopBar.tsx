"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { formatChapter } from "@/lib/anchor";
import { useAsk } from "@/lib/store";
import { PENS, THEMES } from "@/lib/appearance";
import { CatIcon } from "@/components/icons";

type TopBarProps = {
  bookTitle: string;
  activeChapter: string;
  activeHeading: string;
  progress: number;
  onJumpTop: () => void;
  onOpenChapters?: () => void;
  chapters: { chapter: string; heading: string; chunkId: string }[];
  onJumpChunk: (chunkId: string) => void;
};

export default function TopBar({
  bookTitle,
  activeChapter,
  activeHeading,
  progress,
  onJumpTop,
  onOpenChapters,
  chapters,
  onJumpChunk,
}: TopBarProps) {
  const theme = useAsk((s) => s.theme);
  const pen = useAsk((s) => s.pen);
  const readSize = useAsk((s) => s.readSize ?? 18);
  const setTheme = useAsk((s) => s.setTheme);
  const setPen = useAsk((s) => s.setPen);
  const setReadSize = useAsk((s) => s.setReadSize);

  const glossCount = useAsk((s) => s.glosses?.length ?? 0);
  const activeGlossId = useAsk((s) => s.activeGlossId);
  const setActiveGloss = useAsk((s) => s.setActiveGloss);

  const setViewMode = useAsk((s) => s.setViewMode);
  const activeBookId = useAsk((s) => s.activeBookId);
  const openBook = useAsk((s) => s.openBook);
  const booksCatalog = useAsk((s) => s.booksCatalog);

  const [tucked, setTucked] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [chaptersOpen, setChaptersOpen] = useState(false);
  const [bookMenuOpen, setBookMenuOpen] = useState(false);
  const [aaOpen, setAaOpen] = useState(false);

  const chaptersRef = useRef<HTMLDivElement>(null);
  const bookMenuRef = useRef<HTMLDivElement>(null);
  const aaRef = useRef<HTMLDivElement>(null);

  // Auto-tuck on scroll down, reveal on scroll up
  useEffect(() => {
    let lastY = typeof window !== "undefined" ? window.scrollY : 0;
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 8);
      if (Math.abs(y - lastY) < 6) return;
      if (y > lastY && y > 160) {
        setTucked(true);
        setChaptersOpen(false);
        setBookMenuOpen(false);
        setAaOpen(false);
      } else if (y < lastY) {
        setTucked(false);
      }
      lastY = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Dismiss dropdowns on outside click
  useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      if (chaptersRef.current && !chaptersRef.current.contains(e.target as Node)) {
        setChaptersOpen(false);
      }
      if (bookMenuRef.current && !bookMenuRef.current.contains(e.target as Node)) {
        setBookMenuOpen(false);
      }
      if (aaRef.current && !aaRef.current.contains(e.target as Node)) {
        setAaOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  // Circular view transition theme picker
  const pickTheme = (key: (typeof THEMES)[number]["key"], e: MouseEvent<HTMLButtonElement>) => {
    const doc = document as Document & {
      startViewTransition?: (cb: () => void) => {
        ready: Promise<void>;
        finished: Promise<void>;
      };
    };
    const quiet = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!doc.startViewTransition || quiet || key === theme) {
      setTheme(key);
      return;
    }

    const r = e.currentTarget.getBoundingClientRect();
    const w = window.innerWidth;
    const h = window.innerHeight;
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const at = `${((x / w) * 100).toFixed(2)}% ${((y / h) * 100).toFixed(2)}%`;
    const end = (
      (Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) /
        (Math.hypot(w, h) / Math.SQRT2)) *
      100
    ).toFixed(2);

    const root = document.documentElement;
    root.classList.add("theme-swap");

    const vt = doc.startViewTransition(() => {
      setTheme(key);
    });

    vt.ready
      ?.then(() =>
        root.animate(
          { clipPath: [`circle(0% at ${at})`, `circle(${end}% at ${at})`] },
          {
            duration: 520,
            easing: "cubic-bezier(0.22, 1, 0.36, 1)",
            pseudoElement: "::view-transition-new(root)",
          }
        )
      )
      ?.catch(() => {});

    vt.finished?.finally(() => {
      root.classList.remove("theme-swap");
    });
  };

  const handleCycleNotes = () => {
    const list = useAsk.getState().glosses;
    if (!list.length) return;
    const currentIndex = list.findIndex((g) => g.id === activeGlossId);
    const nextIndex = (currentIndex + 1) % list.length;
    const next = list[nextIndex];
    setActiveGloss(next.id);
    const chunkEl = document.querySelector(
      `[data-chunk-id="${CSS.escape(next.chunkId)}"]`
    );
    if (chunkEl) {
      chunkEl.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const chLabel = activeChapter ? formatChapter(activeChapter) : "";
  const currentBook = booksCatalog.find((b) => b.book_id === activeBookId);
  const currentBookTitle = currentBook ? currentBook.title : bookTitle || "Volume";

  return (
    <header
      className={`topbar ${tucked ? "tucked" : ""} ${
        scrolled ? "is-scrolled" : ""
      }`}
    >
      <div className="topbar-inner">
        {/* Left Side: Brand + Library button + Book Switcher + Chapter dropdown */}
        <div className="topbar-left" ref={chaptersRef}>
          <button
            type="button"
            onClick={() => setViewMode("library")}
            className="topbar-brand"
            title="Open NekoHon Library"
            aria-label="Open NekoHon Library"
          >
            <CatIcon size={20} className="topbar-logo-icon" />
            <span className="topbar-brand-name">NekoHon</span>
            <span className="topbar-brand-kanji">猫本</span>
          </button>

          <button
            type="button"
            onClick={() => setViewMode("library")}
            className="topbar-library-btn"
            title="Return to Library Start Menu"
          >
            <span className="topbar-library-arrow">←</span>
            <span className="topbar-library-text">Library</span>
          </button>

          {/* Book Switcher Dropdown */}
          <div className="topbar-book-wrap" ref={bookMenuRef}>
            <button
              type="button"
              onClick={() => setBookMenuOpen((v) => !v)}
              className="topbar-book-btn"
              aria-expanded={bookMenuOpen}
              aria-label="Switch book"
            >
              <span className="topbar-book-label">
                {currentBookTitle}
              </span>
              <span className="topbar-caret">▾</span>
            </button>

            {bookMenuOpen && (
              <div className="topbar-book-menu">
                <div className="topbar-book-menu-title">Volumes on Shelf</div>
                {booksCatalog.map((b) => (
                  <button
                    key={b.book_id}
                    type="button"
                    onClick={() => {
                      openBook(b.book_id);
                      setBookMenuOpen(false);
                    }}
                    className={`topbar-book-item ${
                      b.book_id === activeBookId ? "is-active" : ""
                    }`}
                  >
                    <span className="topbar-book-item-title">{b.title}</span>
                    <span className="topbar-book-item-meta">
                      {b.author} · {b.chunk_count} passages
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Chapter Selector Dropdown */}
          <div className="topbar-toc-wrap">
            <button
              type="button"
              onClick={() => setChaptersOpen((v) => !v)}
              className="topbar-chapter-btn"
              aria-expanded={chaptersOpen}
              aria-label="Select chapter"
            >
              <span className="topbar-chapter-label">
                {chLabel || "Chapters"}
              </span>
              <span className="topbar-caret">▾</span>
            </button>

            {chaptersOpen && (
              <div className="topbar-toc">
                <div className="topbar-toc-title">
                  Table of Contents
                </div>
                {chapters.map((ch) => (
                  <button
                    key={`${ch.chapter}:${ch.chunkId}`}
                    type="button"
                    onClick={() => {
                      onJumpChunk(ch.chunkId);
                      setChaptersOpen(false);
                    }}
                    className={`topbar-toc-item ${
                      ch.chapter === activeChapter ? "is-active" : ""
                    }`}
                  >
                    <span className="topbar-toc-ch">{formatChapter(ch.chapter)}</span>
                    <span className="topbar-toc-heading">
                      {ch.heading || "Introduction"}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Center: Running header */}
        <div className="topbar-running">
          <button
            type="button"
            onClick={onJumpTop}
            className="topbar-running-btn"
            title="Click to jump to chapter top"
          >
            {chLabel}
            {activeHeading && activeHeading.toLowerCase() !== chLabel.toLowerCase()
              ? ` · ${activeHeading}`
              : ""}
          </button>
        </div>

        {/* Right Side: Notes badge + Aa appearance popover */}
        <div className="topbar-right">
          {glossCount > 0 && (
            <button
              type="button"
              onClick={handleCycleNotes}
              className="topbar-notes-btn"
              title="Click to cycle notes"
            >
              <span>{glossCount}</span>
              <span className="topbar-notes-text">
                {glossCount === 1 ? "note" : "notes"}
              </span>
            </button>
          )}

          {/* Aa Appearance Button */}
          <div className="topbar-aa-wrap" ref={aaRef}>
            <button
              type="button"
              onClick={() => setAaOpen((v) => !v)}
              aria-expanded={aaOpen}
              aria-label="Appearance settings"
              className={`topbar-aa-btn ${aaOpen ? "is-active" : ""}`}
            >
              Aa
            </button>

            {aaOpen && (
              <div className="aa-popover">
                {/* Theme section */}
                <div className="aa-section">
                  <div className="aa-label">
                    Theme
                  </div>
                  <div className="aa-theme-grid">
                    {THEMES.map((t) => (
                      <button
                        key={t.key}
                        type="button"
                        onClick={(e) => pickTheme(t.key, e)}
                        className={`aa-theme-btn ${
                          theme === t.key ? "is-active" : ""
                        }`}
                      >
                        <span
                          className="aa-theme-swatch"
                          style={{ background: t.bg, color: t.fg }}
                        >
                          Aa
                        </span>
                        <span className="aa-theme-name">
                          {t.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Pen section */}
                <div className="aa-section">
                  <div className="aa-label">
                    Margin Pen
                  </div>
                  <div className="aa-pen-row">
                    {PENS.map((p) => (
                      <button
                        key={p.key}
                        type="button"
                        onClick={() => setPen(p.key)}
                        aria-label={`${p.label} pen`}
                        className={`aa-pen-dot ${
                          pen === p.key ? "is-active" : ""
                        }`}
                        style={{ background: p.color }}
                      />
                    ))}
                    <span className="aa-pen-name">
                      {pen}
                    </span>
                  </div>
                </div>

                {/* Text Size section */}
                <div className="aa-section">
                  <div className="aa-label">
                    Text Size
                  </div>
                  <div className="aa-size-row">
                    <button
                      type="button"
                      onClick={() => setReadSize(Math.max(15, readSize - 1))}
                      disabled={readSize <= 15}
                      className="aa-size-btn"
                      aria-label="Decrease text size"
                    >
                      −
                    </button>
                    <span className="aa-size-val">
                      {readSize}px
                    </span>
                    <button
                      type="button"
                      onClick={() => setReadSize(Math.min(26, readSize + 1))}
                      disabled={readSize >= 26}
                      className="aa-size-btn"
                      aria-label="Increase text size"
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Progress hairline */}
      <span
        aria-hidden
        className="topbar-progress"
        style={{
          transform: `scaleX(${Math.max(0, Math.min(1, progress))})`,
        }}
      />
    </header>
  );
}
