import { CatIcon } from "@/components/icons";
import type { BookStats } from "@/components/library/BookCard";
import { engineUrl, type BookCatalogItem } from "@/lib/engine";

type BookDetailProps = {
  book: BookCatalogItem;
  stats: BookStats;
  onClose: () => void;
  onOpen: (bookId: string) => void;
};

export default function BookDetail({ book, stats, onClose, onOpen }: BookDetailProps) {
  return (
    <div className="bookopen-modal">
      <div
        className="bookopen-backdrop"
        onClick={onClose}
      />

      <div className="bookopen-spread-wrap">
        <div className="bookopen-spread">
          <button
            type="button"
            onClick={onClose}
            className="bookopen-close-x"
            aria-label="Close Book"
          >
            ×
          </button>

          <div className="bookopen-page is-left">
            <div className="ex-libris-frame">
              {book.cover_url && (
                <img
                  src={`${engineUrl()}${book.cover_url}`}
                  alt={book.title}
                  width={180}
                  height={260}
                  loading="lazy"
                  decoding="async"
                  className="bookplate-cover-thumb"
                />
              )}
              <div className="ex-libris-emblem">
                <CatIcon size={38} className="ex-libris-emblem-svg" />
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
                  <span className="ex-spec-value">{book.chapter_count}</span>
                </div>
                <div className="ex-spec-item">
                  <span className="ex-spec-label">Passages</span>
                  <span className="ex-spec-value">{book.chunk_count}</span>
                </div>
                <div className="ex-spec-item">
                  <span className="ex-spec-label">Figures</span>
                  <span className="ex-spec-value">{book.figure_count}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="bookopen-page is-right">
            <div className="bookopen-content">
              <h2 className="bookopen-title">{book.title}</h2>
              <p className="bookopen-author">{book.author}</p>
              <div className="bookopen-divider" />

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

              <div className="bookopen-stats-chips">
                <span className="bookopen-chip">
                  {stats.highlightsCount} saved highlights
                </span>
                <span className="bookopen-chip">
                  {stats.notesCount} margin notes
                </span>
              </div>

              <div className="bookopen-actions">
                <button
                  type="button"
                  onClick={() => {
                    onClose();
                    onOpen(book.book_id);
                  }}
                  className="bookopen-read-btn"
                >
                  <span>Open Volume & Read</span>
                  <span>→</span>
                </button>
                <button
                  type="button"
                  onClick={onClose}
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
  );
}
