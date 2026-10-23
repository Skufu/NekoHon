import type { BookCatalogItem } from "@/lib/engine";
import BookCard, { type BookStats } from "@/components/library/BookCard";

type GridProps = {
  books: BookCatalogItem[];
  statsMap: Record<string, BookStats>;
  onSelect: (book: BookCatalogItem) => void;
  onOpen: (bookId: string) => void;
};

export default function Grid({ books, statsMap, onSelect, onOpen }: GridProps) {
  return (
    <div className="grid-view">
      {books.map((book) => (
        <BookCard
          key={book.book_id}
          book={book}
          stats={statsMap[book.book_id]}
          variant="grid"
          onSelect={onSelect}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}
