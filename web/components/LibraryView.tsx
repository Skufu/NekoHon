"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { engineUrl, importEpubBook, type BookCatalogItem } from "@/lib/engine";
import { useAsk } from "@/lib/store";
import IngestCard, { displayTitle, type IngestState } from "@/components/IngestCard";

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

function coverSrc(book: BookCatalogItem): string {
  if (!book.cover_url) return "";
  if (/^https?:\/\//i.test(book.cover_url)) return book.cover_url;
  return `${engineUrl()}${book.cover_url}`;
}

function bookMeta(book: BookCatalogItem): string {
  if (book.chapter_count > 0) return `${book.chapter_count} chapters`;
  return "New volume";
}

export default function LibraryView({ loadError = "" }: { loadError?: string }) {
  const booksCatalog = useAsk((s) => s.booksCatalog);
  const bookProgress = useAsk((s) => s.bookProgress);
  const addBookToCatalog = useAsk((s) => s.addBookToCatalog);
  const openBook = useAsk((s) => s.openBook);

  const [searchQuery, setSearchQuery] = useState("");
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [dismissedError, setDismissedError] = useState(false);
  const [importingState, setImportingState] = useState<IngestState>({ status: "idle" });
  const isBusy =
    importingState.status === "reading" ||
    importingState.status === "ingesting" ||
    importingState.status === "done";

  const searchInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const openTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current);
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toUpperCase();
      if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(tag)) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const filteredBooks = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return booksCatalog;
    return booksCatalog.filter(
      (book) =>
        book.title.toLowerCase().includes(q) ||
        book.author.toLowerCase().includes(q) ||
        book.book_id.toLowerCase().includes(q)
    );
  }, [booksCatalog, searchQuery]);

  const handleFile = async (file: File) => {
    if (isBusy) return;

    if (!file.name.toLowerCase().endsWith(".epub")) {
      setImportingState({
        status: "error",
        filename: file.name,
        error: "Choose an .epub file to add it to Nekohon.",
      });
      return;
    }

    setImportingState({ status: "reading", filename: file.name });
    try {
      const reader = new FileReader();
      const base64Promise = new Promise<string>((resolve, reject) => {
        reader.onload = () => {
          const result = reader.result as string;
          const comma = result.indexOf(",");
          resolve(comma >= 0 ? result.slice(comma + 1) : result);
        };
        reader.onerror = () => reject(new Error("The file could not be read."));
      });
      reader.readAsDataURL(file);
      const base64 = await base64Promise;

      setImportingState({ status: "ingesting", filename: file.name });
      const result = await importEpubBook(file.name, base64);
      if (result.ok && result.book_id) {
        const bookToAdd: BookCatalogItem = result.book || {
          book_id: result.book_id,
          title: displayTitle(file.name),
          author: "Imported from this machine",
          chapter_count: 0,
          chunk_count: 0,
          figure_count: 0,
        };
        addBookToCatalog(bookToAdd);
        setImportingState({ status: "done", filename: file.name });
        openTimerRef.current = window.setTimeout(() => {
          openTimerRef.current = null;
          setImportingState({ status: "idle" });
          openBook(result.book_id);
        }, 650);
      } else {
        setImportingState({
          status: "error",
          filename: file.name,
          error: result.error || "The engine could not read that EPUB.",
        });
      }
    } catch (error: unknown) {
      setImportingState({
        status: "error",
        filename: file.name,
        error:
          error instanceof Error && error.name === "TimeoutError"
            ? "The local engine did not answer within 10 minutes. It may still be ingesting; reload the library to check."
            : error instanceof TypeError
              ? "Could not reach the local engine on :8000. Start it, then try again."
              : error instanceof Error
                ? error.message
                : "Import failed.",
      });
    }
  };

  const onDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (isBusy) return;
    setIsDraggingFile(true);
  };

  const onDragLeave = () => {
    setIsDraggingFile(false);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDraggingFile(false);
    const file = event.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const onFileInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) handleFile(file);
    event.target.value = "";
  };

  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setSearchQuery("");
      event.currentTarget.blur();
    }
  };

  return (
    <div
      className="nekohon-library"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".epub"
        onChange={onFileInputChange}
        className="nk-file-input"
        aria-hidden="true"
        tabIndex={-1}
      />

      <div className="nk-lib-shell">
        <header className="nk-lib-top">
          <div className="nk-lib-brand">
            <span className="nk-lib-logo">
              <img
                src="/nekohon-mark.svg"
                alt=""
                width={36}
                height={36}
                className="nk-lib-logo-img"
              />
            </span>
            <span className="nk-lib-brand-text">
              <span className="nk-lib-wordmark">Nekohon</span>
              <span className="nk-lib-sublabel">Local library</span>
            </span>
          </div>

          <div className="nk-lib-tools">
            <div className="nk-search">
              <svg
                viewBox="0 0 24 24"
                width="16"
                height="16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                className="nk-search-icon"
                aria-hidden
              >
                <circle cx="11" cy="11" r="6.5" />
                <path d="M16 16l4 4" />
              </svg>
              <input
                ref={searchInputRef}
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onKeyDown={onSearchKeyDown}
                placeholder="Search titles or authors…"
                aria-label="Search the library"
                autoComplete="off"
                spellCheck={false}
                className="nk-search-input"
              />
              <kbd className="nk-kbd" aria-hidden>
                /
              </kbd>
            </div>
            <button
              type="button"
              className="nk-add"
              onClick={() => fileInputRef.current?.click()}
              aria-label="Add an EPUB to the library"
              disabled={isBusy}
            >
              <svg
                viewBox="0 0 24 24"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                className="nk-add-icon"
                aria-hidden
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
              Add book
            </button>
          </div>
        </header>

        <section className="nk-lib-intro">
          <h1 className="nk-lib-heading">Books to read</h1>
        </section>

        <IngestCard
          state={importingState}
          onDismiss={() => setImportingState({ status: "idle" })}
        />

        {loadError && !dismissedError && (
          <div className="nk-alert" role="alert">
            <svg
              viewBox="0 0 20 20"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="nk-alert-icon"
              aria-hidden
            >
              <circle cx="10" cy="10" r="8" />
              <path d="M10 6v5M10 14.5v0" />
            </svg>
            <div className="nk-alert-body">
              <span className="nk-alert-title">Local engine disconnected</span>
              <span className="nk-alert-text">
                Could not connect to :8000. Start the local engine, then retry.
              </span>
            </div>
            <div className="nk-alert-actions">
              <button
                type="button"
                className="nk-alert-retry"
                onClick={() => window.location.reload()}
              >
                Retry
              </button>
              <button
                type="button"
                className="nk-alert-dismiss"
                onClick={() => setDismissedError(true)}
                aria-label="Dismiss error notification"
              >
                <svg
                  viewBox="0 0 16 16"
                  width="13"
                  height="13"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden
                >
                  <path d="M4 4l8 8M12 4l-8 8" />
                </svg>
              </button>
            </div>
          </div>
        )}

        {filteredBooks.length > 0 ? (
          <section className="nk-shelf" aria-label="Your library">
            {filteredBooks.map((book) => {
              const cloth = bookCloth(book.book_id);
              const src = coverSrc(book);
              const progress = bookProgress[book.book_id]?.pct ?? 0;
              return (
                <button
                  key={book.book_id}
                  type="button"
                  className="nk-book"
                  onClick={() => openBook(book.book_id)}
                  aria-label={`Open ${book.title}`}
                >
                  <span
                    className="nk-book-cover"
                    style={{ background: cloth.bg, color: cloth.fg }}
                  >
                    {src ? (
                      <img
                        src={src}
                        alt=""
                        loading="lazy"
                        className="nk-book-cover-img"
                        onError={(event) => {
                          event.currentTarget.style.display = "none";
                        }}
                      />
                    ) : null}
                    <span className="nk-book-fallback" aria-hidden>
                      <span className="nk-book-fallback-title">{book.title}</span>
                      <span className="nk-book-fallback-author">{book.author}</span>
                    </span>
                    {progress > 0.005 ? (
                      <span
                        className="nk-book-progress"
                        style={{ width: `${Math.min(100, Math.round(progress * 100))}%` }}
                        aria-hidden
                      />
                    ) : null}
                  </span>
                  <span className="nk-book-title" title={book.title}>
                    {book.title}
                  </span>
                  <span className="nk-book-author" title={book.author}>
                    {book.author}
                  </span>
                  <span className="nk-book-meta">{bookMeta(book)}</span>
                  {progress > 0.005 ? (
                    <span className="nk-book-reading">
                      <span className="nk-book-reading-dot" aria-hidden />
                      Reading · {Math.round(progress * 100)}%
                    </span>
                  ) : null}
                </button>
              );
            })}
          </section>
        ) : booksCatalog.length > 0 ? (
          <div className="nk-empty">
            <h2 className="nk-empty-title">No volumes match “{searchQuery.trim()}”.</h2>
            <p className="nk-empty-text">Try a title, an author, or a word from the cover.</p>
            <button
              type="button"
              className="nk-empty-action"
              onClick={() => setSearchQuery("")}
            >
              Clear search
            </button>
          </div>
        ) : (
          <div className="nk-empty nk-empty-first">
            <h2 className="nk-empty-title">
              {loadError ? "Engine offline" : "Your shelf is empty"}
            </h2>
            <p className="nk-empty-text">
              {loadError
                ? "Start the local engine on :8000 to connect to your library."
                : "Drop an EPUB anywhere on this screen, or browse your files to add a volume."}
            </p>
            <button
              type="button"
              className="nk-empty-action"
              onClick={() => {
                if (loadError) {
                  window.location.reload();
                } else {
                  fileInputRef.current?.click();
                }
              }}
              disabled={isBusy}
            >
              {loadError ? "Retry connection" : "Add an EPUB"}
            </button>
          </div>
        )}

      </div>

      {isDraggingFile && (
        <div className="nk-drop" aria-hidden>
          <div className="nk-drop-inner">
            <span className="nk-drop-title">Drop to shelve</span>
            <span className="nk-drop-sub">An .epub stays on this machine.</span>
          </div>
        </div>
      )}
    </div>
  );
}
