"""Per-chapter chunk coverage for every book in the catalog. Read-only.

Index resolution mirrors server.get_book_index: the catalog's first entry
(`fde`) is served by retrieve.INDEX (data/index.json), every other book by
data/index.<book_id>.json when that file exists, else by its catalog
`index_path`. The catalog is the source of truth for which books exist; the
index files are the source of truth for the counts printed here. Nothing is
written and no model is called.

Run: python artifacts/probes/coverage-map-2026-10-23.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "data" / "books.json"
DEFAULT_INDEX = ROOT / "data" / "index.json"
DEFAULT_BOOK_ID = "fde"
THIN = 3


def load_catalog():
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    books = raw if isinstance(raw, list) else raw.get("books", [])
    return [book for book in books if isinstance(book, dict) and book.get("book_id")]


def index_path_for(book):
    book_id = book["book_id"]
    if book_id == DEFAULT_BOOK_ID:
        return DEFAULT_INDEX
    candidate = ROOT / "data" / f"index.{book_id}.json"
    if candidate.is_file():
        return candidate
    declared = book.get("index_path")
    if declared:
        path = Path(declared)
        return path if path.is_absolute() else ROOT / path
    return None


def chapter_sort_key(chapter):
    """Numeric chapters in numeric order, then the rest by name."""
    text = "" if chapter is None else str(chapter)
    if text.isdigit():
        return (0, int(text), text)
    return (1, 0, text)


def chapter_rows(index):
    counts = {}
    for chunk in index.get("chunks") or []:
        chapter = chunk.get("chapter")
        if chapter is None or str(chapter).strip() == "":
            chapter = "(none)"
        counts[chapter] = counts.get(chapter, 0) + 1
    return [(chapter, counts[chapter]) for chapter in sorted(counts, key=chapter_sort_key)]


def print_book(book, path, index):
    chunks = index.get("chunks") or []
    figures = index.get("figures") or []
    rows = chapter_rows(index)
    thin = [(chapter, count) for chapter, count in rows if count < THIN]

    print()
    print(f"book: {book['book_id']} - {book.get('title') or ''}")
    print(f"index: {path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path}")
    print()

    header = ("chapter", "chunks")
    width = max([len(header[0])] + [len(str(chapter)) for chapter, _ in rows])
    print(f"  {header[0].ljust(width)}  {header[1]:>6}")
    print(f"  {'-' * width}  {'-' * 6}")
    for chapter, count in rows:
        print(f"  {str(chapter).ljust(width)}  {count:>6}")
    print(f"  {'-' * width}  {'-' * 6}")
    print(f"  {'TOTAL'.ljust(width)}  {len(chunks):>6}")
    print()
    print(
        f"  totals: chapters {len(rows)}  chunks {len(chunks)}  "
        f"figures {len(figures)}  "
        f"catalog says chapters {book.get('chapter_count')} / chunks {book.get('chunk_count')}"
    )
    print(f"  chapters with fewer than {THIN} chunks: {len(thin)}")
    if thin:
        print("  " + ", ".join(f"{chapter} ({count})" for chapter, count in thin))
    return rows, len(chunks), len(thin)


def main():
    books = load_catalog()
    if not books:
        raise SystemExit(f"no books in {CATALOG}")

    total_chapters = 0
    total_chunks = 0
    total_thin = 0
    measured = 0

    for book in books:
        path = index_path_for(book)
        if path is None or not path.is_file():
            print()
            print(f"book: {book['book_id']} - {book.get('title') or ''}")
            print(f"  MISSING index: {path if path is not None else 'no path in catalog'}")
            continue
        index = json.loads(path.read_text(encoding="utf-8"))
        rows, chunks, thin_count = print_book(book, path, index)
        total_chapters += len(rows)
        total_chunks += chunks
        total_thin += thin_count
        measured += 1

    print()
    print(
        f"TOTAL: books {measured}  chapters {total_chapters}  chunks {total_chunks}  "
        f"chapters with fewer than {THIN} chunks: {total_thin}"
    )


if __name__ == "__main__":
    main()
