"use client";

import { useEffect, useMemo, useRef, useState, type DragEvent, type ChangeEvent } from "react";
import { importEpubBook, engineUrl, type BookCatalogItem } from "@/lib/engine";
import { useAsk, type ThemeName } from "@/lib/store";

const THEMES: { key: ThemeName; label: string; swatch: string }[] = [
  { key: "night", label: "Night", swatch: "var(--swatch-night-bg)" },
  { key: "paper", label: "Paper", swatch: "var(--swatch-paper-bg)" },
  { key: "sepia", label: "Sepia", swatch: "var(--swatch-sepia-bg)" },
  { key: "snow", label: "Snow", swatch: "var(--swatch-snow-bg)" },
  { key: "ink", label: "Ink", swatch: "var(--swatch-ink-bg)" },
];

function bookCloth(bookId: string): { bg: string; fg: string } {
  if (bookId === "fde") {
    return { bg: "var(--cloth-terracotta)", fg: "var(--cloth-terracotta-fg)" };
  }
  if (bookId === "ddia") {
    return { bg: "var(--cloth-navy)", fg: "var(--cloth-navy-fg)" };
  }
  if (bookId === "quantization") {
    return { bg: "var(--cloth-sage)", fg: "var(--cloth-sage-fg)" };
  }
  return { bg: "var(--cloth-plum)", fg: "var(--cloth-plum-fg)" };
}

export default function LibraryView() {
  const booksCatalog = useAsk((s) => s.booksCatalog);
  const addBookToCatalog = useAsk((s) => s.addBookToCatalog);
  const openBook = useAsk((s) => s.openBook);
  const getBookStats = useAsk((s) => s.getBookStats);
  const theme = useAsk((s) => s.theme);
  const setTheme = useAsk((s) => s.setTheme);

  const [searchQuery, setSearchQuery] = useState("");
  const [viewType, setViewType] = useState<"shelf" | "grid">("shelf");
  const [selectedBook, setSelectedBook] = useState<BookCatalogItem | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [importingState, setImportingState] = useState<{
    status: "idle" | "reading" | "ingesting" | "done" | "error";
    filename?: string;
    error?: string;
  }>({ status: "idle" });

  const searchInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Focus search with '/' key
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

  // Filter books by query
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

  // Aggregate stats
  const totalChapters = useMemo(
    () => booksCatalog.reduce((sum, b) => sum + (b.chapter_count || 0), 0),
    [booksCatalog]
  );
  const totalChunks = useMemo(
    () => booksCatalog.reduce((sum, b) => sum + (b.chunk_count || 0), 0),
    [booksCatalog]
  );

  // File import handler
  const handleFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".epub")) {
      setImportingState({
        status: "error",
        error: "Please select an .epub file to import into NekoHon.",
      });
      return;
    }

    setImportingState({ status: "reading", filename: file.name });
    try {
      const reader = new FileReader();
      const base64Promise = new Promise<string>((resolve, reject) => {
        reader.onload = () => {
          const res = reader.result as string;
          const comma = res.indexOf(",");
          resolve(comma >= 0 ? res.slice(comma + 1) : res);
        };
        reader.onerror = () => reject(new Error("Failed to read file"));
      });
      reader.readAsDataURL(file);
      const base64 = await base64Promise;

      setImportingState({ status: "ingesting", filename: file.name });
      const result = await importEpubBook(file.name, base64);
      if (result.ok && result.book_id) {
        const cleanTitle = file.name
          .replace(/\.epub$/i, "")
          .replace(/[-_]/g, " ")
          .trim();
        const bookToAdd: BookCatalogItem = result.book || {
          book_id: result.book_id,
          title: cleanTitle || "Imported Volume",
          author: "Local Reader Ingestion",
          chapter_count: 10,
          chunk_count: 450,
          figure_count: 15,
        };
        addBookToCatalog(bookToAdd);
        setImportingState({ status: "done", filename: file.name });
        setTimeout(() => {
          setImportingState({ status: "idle" });
          openBook(result.book_id);
        }, 600);
      } else {
        setImportingState({
          status: "error",
          error: result.error || "Engine could not parse the EPUB.",
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Import failed";
      setImportingState({ status: "error", error: msg });
    }
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingFile(true);
  };

  const onDragLeave = () => {
    setIsDraggingFile(false);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingFile(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  };

  const onFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
  };

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

      {/* Drag & Drop Overlay */}
      {isDraggingFile && (
        <div className="drop-overlay">
          <div className="drop-card">
            <svg
              viewBox="0 0 24 24"
              width="44"
              height="44"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="drop-icon"
              aria-hidden
            >
              <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
              <path d="M12 6v6" />
              <path d="m9 9 3-3 3 3" />
            </svg>
            <div className="drop-title">Drop .epub to ingest into NekoHon</div>
            <div className="drop-sub">Local embedding and passage chunking via Ollama</div>
          </div>
        </div>
      )}

      {/* Ingestion In-Progress / Error Card */}
      {importingState.status !== "idle" && (
        <div className="ingest-modal">
          <div className="ingest-card">
            {importingState.status === "reading" || importingState.status === "ingesting" ? (
              <>
                <div className="ingest-spinner" aria-hidden />
                <div className="ingest-title">
                  {importingState.status === "reading"
                    ? "Reading EPUB package…"
                    : "Ingesting & embedding passages locally…"}
                </div>
                <div className="ingest-sub">{importingState.filename}</div>
              </>
            ) : importingState.status === "done" ? (
              <>
                <div className="ingest-title">Volume Shelved Successfully</div>
                <div className="ingest-sub">Opening reader view…</div>
              </>
            ) : (
              <>
                <div className="ingest-title">Ingestion Error</div>
                <div className="ingest-error-text">{importingState.error}</div>
                <button
                  type="button"
                  onClick={() => setImportingState({ status: "idle" })}
                  className="ingest-close-btn"
                >
                  Close
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Top Editorial Header */}
      <header className="library-hero">
        <div className="library-brand-row">
          <div className="library-mark-wrap">
            <svg
              viewBox="0 0 24 24"
              width="36"
              height="36"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="library-cat-icon"
              aria-hidden
            >
              <path d="M2 18c3-1.5 6-1.5 10 0 4-1.5 7-1.5 10 0v-11c-3-1.5-6-1.5-10 0-4-1.5-7-1.5-10 0v11z" />
              <path d="M12 7v11" />
              <path d="M7 6c0-2 2-3.5 4-3.5s3.5 1 4 2.5" />
              <path d="M9 2.5L9.5 4" />
              <path d="M13.5 2.5L13 4" />
              <path d="M15 5c1.5 0 2.5.8 2.5 2" />
            </svg>
          </div>
          <div className="library-title-group">
            <h1 className="library-title">NekoHon</h1>
            <p className="library-subtitle">Local Book Companion · 猫本</p>
          </div>
        </div>

        {/* Live Library Stats Ribbon */}
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

        {/* Controls Toolbar */}
        <div className="library-controls">
          {/* Search Bar */}
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

          {/* View Switcher: Shelf vs Grid */}
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

          {/* Theme Quick Toggle */}
          <div className="library-theme-toggle">
            {THEMES.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTheme(t.key)}
                className={`library-theme-btn ${theme === t.key ? "is-active" : ""}`}
                style={{ background: t.swatch }}
                title={`Switch to ${t.label} theme`}
                aria-label={`Switch to ${t.label} theme`}
              />
            ))}
          </div>

          {/* Primary + Add Book (.epub) */}
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

      {/* Bookcase / Shelf View */}
      <main className="library-content">
        {filteredBooks.length === 0 ? (
          <div className="empty-shelf">
            <p className="empty-shelf-text">
              No volumes matching &ldquo;{searchQuery}&rdquo;
            </p>
          </div>
        ) : viewType === "shelf" ? (
          <div className="shelf-view">
            <div className="shelf-bookcase">
              <div className="shelf-run">
                {filteredBooks.map((book) => {
                  const cloth = bookCloth(book.book_id);
                  const stats = getBookStats(book.book_id);
                  return (
                    <div key={book.book_id} className="shelf-book-item">
                      <button
                        type="button"
                        onClick={() => setSelectedBook(book)}
                        className="spine-book-btn"
                        style={{
                          background: cloth.bg,
                          color: cloth.fg,
                        }}
                        title={`${book.title} · ${book.author}`}
                      >
                        {stats.pct > 0 && <span className="spine-ribbon" aria-hidden />}
                        <span className="spine-foil-ornament">◆</span>
                        <div className="spine-title-wrap">
                          <span className="spine-title">{book.title}</span>
                        </div>
                        <span className="spine-author">{book.author.split("&")[0].trim()}</span>
                      </button>
                    </div>
                  );
                })}

                {/* Shelf Bookend */}
                <div className="shelf-bookend" aria-hidden>
                  <svg
                    viewBox="0 0 28 64"
                    width="28"
                    height="64"
                    fill="currentColor"
                    className="shelf-bookend-svg"
                  >
                    <path d="M4 64V24C4 12 12 4 24 4h4v60H4z" />
                  </svg>
                </div>

                {/* Decorative Ceramic Plant / Foliage Ornament */}
                <div className="shelf-ornament" aria-hidden>
                  <svg viewBox="0 0 48 72" width="48" height="72" fill="none" stroke="currentColor">
                    <path d="M12 48h24l-4 22H16l-4-22z" fill="var(--cloth-sage)" strokeWidth="1.5" />
                    <path d="M24 48V18" stroke="var(--cloth-sage)" strokeWidth="2" />
                    <path d="M24 32c-8-4-12-14-12-22 10 0 16 8 12 22z" fill="var(--cloth-sage)" />
                    <path d="M24 24c8-4 12-14 12-20-10 0-16 8-12 20z" fill="var(--cloth-sage)" />
                  </svg>
                </div>
              </div>

              {/* Wooden Shelf Plank */}
              <div className="shelf-plank">
                <div className="shelf-plank-edge" />
              </div>
            </div>
          </div>
        ) : (
          /* Grid View */
          <div className="grid-view">
            {filteredBooks.map((book) => {
              const cloth = bookCloth(book.book_id);
              const stats = getBookStats(book.book_id);
              return (
                <div key={book.book_id} className="grid-card">
                  {/* Generative Typographic Cloth Cover */}
                  <div
                    className="grid-cover-wrap"
                    onClick={() => setSelectedBook(book)}
                  >
                    <div
                      className="grid-cover"
                      style={{
                        background: cloth.bg,
                        color: cloth.fg,
                      }}
                    >
                      <div className="grid-cover-border" />
                      {stats.pct > 0 && <span className="grid-cover-ribbon" aria-hidden />}
                      <div className="grid-cover-title">{book.title}</div>
                      <div className="grid-cover-author">{book.author}</div>
                    </div>
                  </div>

                  {/* Editorial Card Body */}
                  <div className="grid-card-body">
                    <div className="grid-card-meta">
                      <span className="grid-stat-tag">
                        {book.chapter_count} chapters
                      </span>
                      <span className="grid-stat-tag">
                        {book.chunk_count} passages
                      </span>
                      {stats.highlightsCount > 0 && (
                        <span className="grid-stat-tag">
                          {stats.highlightsCount} highlights
                        </span>
                      )}
                    </div>

                    {/* Reading Progress */}
                    <div className="grid-progress-wrap">
                      <div className="grid-progress-bar">
                        <div
                          className="grid-progress-fill"
                          style={{ width: `${Math.round(stats.pct * 100)}%` }}
                        />
                      </div>
                      <div className="grid-progress-text">
                        {stats.pct > 0
                          ? `${Math.round(stats.pct * 100)}% read`
                          : "Unread"}
                      </div>
                    </div>

                    <div className="grid-card-actions">
                      <button
                        type="button"
                        onClick={() => setSelectedBook(book)}
                        className="grid-inspect-btn"
                      >
                        Inspect Bookplate
                      </button>
                      <button
                        type="button"
                        onClick={() => openBook(book.book_id)}
                        className="grid-read-btn"
                      >
                        <span>Open & Read</span>
                        <span>→</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* 3D BookOpen Modal Spread */}
      {selectedBook && (
        <div className="bookopen-modal">
          <div
            className="bookopen-backdrop"
            onClick={() => setSelectedBook(null)}
          />

          <div className="bookopen-spread-wrap">
            <div className="bookopen-spread">
              <button
                type="button"
                onClick={() => setSelectedBook(null)}
                className="bookopen-close-x"
                aria-label="Close Book"
              >
                ×
              </button>

              {/* Left Page: Ex Libris Bookplate */}
              <div className="bookopen-page is-left">
                <div className="ex-libris-frame">
                  {selectedBook.cover_url && (
                    <img
                      src={`${engineUrl()}${selectedBook.cover_url}`}
                      alt={selectedBook.title}
                      width={180}
                      height={260}
                      loading="lazy"
                      decoding="async"
                      className="bookplate-cover-thumb"
                    />
                  )}
                  <div className="ex-libris-emblem">
                    <svg
                      viewBox="0 0 24 24"
                      width="38"
                      height="38"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="ex-libris-emblem-svg"
                      aria-hidden
                    >
                      <path d="M2 18c3-1.5 6-1.5 10 0 4-1.5 7-1.5 10 0v-11c-3-1.5-6-1.5-10 0-4-1.5-7-1.5-10 0v11z" />
                      <path d="M12 7v11" />
                      <path d="M7 6c0-2 2-3.5 4-3.5s3.5 1 4 2.5" />
                      <path d="M9 2.5L9.5 4" />
                      <path d="M13.5 2.5L13 4" />
                      <path d="M15 5c1.5 0 2.5.8 2.5 2" />
                    </svg>
                  </div>
                  <div className="ex-libris-title">EX LIBRIS · NEKOHON</div>
                  <div className="ex-libris-owner-label">From the local collection of</div>
                  <div className="ex-libris-owner-name">Private Reader & Scholar</div>
                  <div className="ex-libris-rule" />
                  <div className="ex-libris-meta">Offline Knowledge Vault</div>

                  <div className="ex-libris-specs">
                    <div className="ex-spec-item">
                      <span className="ex-spec-label">Embedder</span>
                      <span className="ex-spec-value">nomic-embed-text</span>
                    </div>
                    <div className="ex-spec-item">
                      <span className="ex-spec-label">Chapters</span>
                      <span className="ex-spec-value">{selectedBook.chapter_count}</span>
                    </div>
                    <div className="ex-spec-item">
                      <span className="ex-spec-label">Passages</span>
                      <span className="ex-spec-value">{selectedBook.chunk_count}</span>
                    </div>
                    <div className="ex-spec-item">
                      <span className="ex-spec-label">Figures</span>
                      <span className="ex-spec-value">{selectedBook.figure_count}</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Page: Title & Action */}
              <div className="bookopen-page is-right">
                <div className="bookopen-content">
                  <h2 className="bookopen-title">{selectedBook.title}</h2>
                  <p className="bookopen-author">{selectedBook.author}</p>
                  <div className="bookopen-divider" />

                  {/* Reading Progress */}
                  {(() => {
                    const stats = getBookStats(selectedBook.book_id);
                    return (
                      <>
                        <div className="bookopen-progress-section">
                          <div className="bookopen-progress-label">
                            <span>Reading Progress</span>
                            <span>{Math.round(stats.pct * 100)}%</span>
                          </div>
                          <div className="bookopen-progress-bar">
                            <div
                              className="bookopen-progress-fill"
                              style={{ width: `${Math.round(stats.pct * 100)}%` }}
                            />
                          </div>
                        </div>

                        {/* Marginalia Counters */}
                        <div className="bookopen-stats-chips">
                          <span className="bookopen-chip">
                            {stats.highlightsCount} saved highlights
                          </span>
                          <span className="bookopen-chip">
                            {stats.notesCount} margin notes
                          </span>
                        </div>
                      </>
                    );
                  })()}

                  <div className="bookopen-actions">
                    <button
                      type="button"
                      onClick={() => {
                        const bookId = selectedBook.book_id;
                        setSelectedBook(null);
                        openBook(bookId);
                      }}
                      className="bookopen-read-btn"
                    >
                      <span>Open Volume & Read</span>
                      <span>→</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedBook(null)}
                      className="bookopen-dismiss-btn"
                    >
                      <span>Put back on shelf</span>
                      <kbd className="bookopen-kbd">Esc</kbd>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
