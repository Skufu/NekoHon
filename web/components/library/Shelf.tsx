import type { BookCatalogItem } from "@/lib/engine";
import BookCard, { type BookStats } from "@/components/library/BookCard";

type ShelfProps = {
  books: BookCatalogItem[];
  statsMap: Record<string, BookStats>;
  onSelect: (book: BookCatalogItem) => void;
};

export default function Shelf({ books, statsMap, onSelect }: ShelfProps) {
  return (
    <div className="shelf-view">
      <div className="shelf-bookcase">
        <div className="shelf-run">
          {books.map((book) => (
            <BookCard
              key={book.book_id}
              book={book}
              stats={statsMap[book.book_id]}
              variant="shelf"
              onSelect={onSelect}
            />
          ))}

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

          <div className="shelf-ornament" aria-hidden>
            <svg viewBox="0 0 48 72" width="48" height="72" fill="none" stroke="currentColor">
              <path d="M12 48h24l-4 22H16l-4-22z" fill="var(--cloth-sage)" strokeWidth="1.5" />
              <path d="M24 48V18" stroke="var(--cloth-sage)" strokeWidth="2" />
              <path d="M24 32c-8-4-12-14-12-22 10 0 16 8 12 22z" fill="var(--cloth-sage)" />
              <path d="M24 24c8-4 12-14 12-20-10 0-16 8-12 20z" fill="var(--cloth-sage)" />
            </svg>
          </div>
        </div>

        <div className="shelf-plank">
          <div className="shelf-plank-edge" />
        </div>
      </div>
    </div>
  );
}
