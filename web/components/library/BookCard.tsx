import type { BookCatalogItem } from "@/lib/engine";
import { useAsk } from "@/lib/store";

export type BookStats = ReturnType<ReturnType<typeof useAsk.getState>["getBookStats"]>;

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

type BookCardProps = {
  book: BookCatalogItem;
  stats: BookStats;
  variant: "shelf" | "grid";
  onSelect: (book: BookCatalogItem) => void;
  onOpen?: (bookId: string) => void;
};

export default function BookCard({ book, stats, variant, onSelect, onOpen }: BookCardProps) {
  const cloth = bookCloth(book.book_id);

  if (variant === "shelf") {
    return (
      <div className="shelf-book-item">
        <button
          type="button"
          onClick={() => onSelect(book)}
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
  }

  return (
    <div className="grid-card">
      <div
        className="grid-cover-wrap"
        onClick={() => onSelect(book)}
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
            onClick={() => onSelect(book)}
            className="grid-inspect-btn"
          >
            Inspect Bookplate
          </button>
          <button
            type="button"
            onClick={() => onOpen?.(book.book_id)}
            className="grid-read-btn"
          >
            <span>Open & Read</span>
            <span>→</span>
          </button>
        </div>
      </div>
    </div>
  );
}
