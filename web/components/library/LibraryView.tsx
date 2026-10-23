"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import BookDetail from "@/components/library/BookDetail";
import Grid from "@/components/library/Grid";
import ImportDrop, { useEpubImport } from "@/components/library/ImportDrop";
import Shelf from "@/components/library/Shelf";
import type { BookCatalogItem } from "@/lib/engine";
import { useAsk } from "@/lib/store";
import { THEMES } from "@/lib/appearance";
import { CatIcon } from "@/components/icons";

export default function LibraryView() {
  const booksCatalog = useAsk((s) => s.booksCatalog);
  const openBook = useAsk((s) => s.openBook);
  const getBookStats = useAsk((s) => s.getBookStats);
  const activeBookId = useAsk((s) => s.activeBookId);
  const highlightsLen = useAsk((s) => s.highlights.length);
  const glossesLen = useAsk((s) => s.glosses.length);
  const bookProgress = useAsk((s) => s.bookProgress);
  const theme = useAsk((s) => s.theme);
  const setTheme = useAsk((s) => s.setTheme);

  const {
    isDraggingFile,
    importingState,
    dismissImport,
    onDragOver,
    onDragLeave,
    onDrop,
    onFileInputChange,
  } = useEpubImport();

  const [searchQuery, setSearchQuery] = useState("");
  const [viewType, setViewType] = useState<"shelf" | "grid">("shelf");
  const [selectedBook, setSelectedBook] = useState<BookCatalogItem | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === "/" &&
        document.activeElement !== searchInputRef.current &&
        !["INPUT", "TEXTAREA"].includes((document.activeElement?.tagName || "").toUpperCase())
      ) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
      if (e.key === "Escape") {
        if (selectedBook) {
          setSelectedBook(null);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedBook]);

  const statsMap = useMemo(() => {
    const out: Record<string, ReturnType<typeof getBookStats>> = {};
    for (const b of booksCatalog) out[b.book_id] = getBookStats(b.book_id);
    return out;
  }, [booksCatalog, getBookStats, activeBookId, highlightsLen, glossesLen, bookProgress]);

  const filteredBooks = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return booksCatalog;
    return booksCatalog.filter(
      (b) =>
        b.title.toLowerCase().includes(q) ||
        b.author.toLowerCase().includes(q) ||
        b.book_id.toLowerCase().includes(q)
    );
  }, [booksCatalog, searchQuery]);

  const totalChapters = useMemo(
    () => booksCatalog.reduce((sum, b) => sum + (b.chapter_count || 0), 0),
    [booksCatalog]
  );
  const totalChunks = useMemo(
    () => booksCatalog.reduce((sum, b) => sum + (b.chunk_count || 0), 0),
    [booksCatalog]
  );

  return (
    <div
      className="library-view"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".epub"
        onChange={onFileInputChange}
        className="hidden-file-input"
        aria-hidden
      />

      <ImportDrop
        isDraggingFile={isDraggingFile}
        importingState={importingState}
        onDismiss={dismissImport}
      />

      <header className="library-hero">
        <div className="library-brand-row">
          <div className="library-mark-wrap">
            <CatIcon size={36} className="library-cat-icon" />
          </div>
          <div className="library-title-group">
            <h1 className="library-title">NekoHon</h1>
            <p className="library-subtitle">Local Book Companion · 猫本</p>
          </div>
        </div>

        <div className="library-stats-ribbon">
          <span className="library-stat-pill">
            {booksCatalog.length} volumes shelved
          </span>
          <span className="library-stat-pill">
            {totalChapters} chapters
          </span>
          <span className="library-stat-pill">
            {totalChunks.toLocaleString()} passages indexed
          </span>
          <span className="library-stat-pill">
            100% local
          </span>
        </div>

        <div className="library-controls">

          <div className="library-search-wrap">
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="library-search-icon"
              aria-hidden
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter by title or author…"
              className="library-search-input"
            />
            <kbd className="library-search-kbd">/</kbd>
          </div>

          <div className="library-view-switcher">
            <button
              type="button"
              onClick={() => setViewType("shelf")}
              className={`library-view-btn ${viewType === "shelf" ? "is-active" : ""}`}
              aria-label="Shelf View"
            >
              <svg
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="library-view-icon"
                aria-hidden
              >
                <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                <path d="M6 6h10" />
                <path d="M6 10h10" />
              </svg>
              <span>Shelf</span>
            </button>
            <button
              type="button"
              onClick={() => setViewType("grid")}
              className={`library-view-btn ${viewType === "grid" ? "is-active" : ""}`}
              aria-label="Grid View"
            >
              <svg
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="library-view-icon"
                aria-hidden
              >
                <rect width="7" height="7" x="3" y="3" rx="1" />
                <rect width="7" height="7" x="14" y="3" rx="1" />
                <rect width="7" height="7" x="14" y="14" rx="1" />
                <rect width="7" height="7" x="3" y="14" rx="1" />
              </svg>
              <span>Grid</span>
            </button>
          </div>

          <div className="library-theme-toggle">
            {THEMES.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTheme(t.key)}
                className={`library-theme-btn ${theme === t.key ? "is-active" : ""}`}
                style={{ background: t.bg }}
                title={`Switch to ${t.label} theme`}
                aria-label={`Switch to ${t.label} theme`}
              />
            ))}
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="library-add-btn"
          >
            <span className="library-add-plus">+</span>
            <span>Add Book (.epub)</span>
          </button>
        </div>
      </header>

      <main className="library-content">
        {filteredBooks.length === 0 ? (
          <div className="empty-shelf">
            <p className="empty-shelf-text">
              No volumes matching &ldquo;{searchQuery}&rdquo;
            </p>
          </div>
        ) : viewType === "shelf" ? (
          <Shelf
            books={filteredBooks}
            statsMap={statsMap}
            onSelect={setSelectedBook}
          />
        ) : (
          <Grid
            books={filteredBooks}
            statsMap={statsMap}
            onSelect={setSelectedBook}
            onOpen={openBook}
          />
        )}
      </main>

      {selectedBook && (
        <BookDetail
          book={selectedBook}
          stats={statsMap[selectedBook.book_id]}
          onClose={() => setSelectedBook(null)}
          onOpen={openBook}
        />
      )}
    </div>
  );
}
