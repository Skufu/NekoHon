"""Dump candidate passages for authoring a hard multi-turn bench (2026-10-24).

Read-only. Prints one passage per ~90 chunks, spread across the three books, so
the bench author can write questions from the text instead of from memory.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEXES = {
    "fde": ROOT / "data" / "index.json",
    "quantization": ROOT / "data" / "index.quantization.json",
    "ddia": ROOT / "data" / "index.ddia.json",
}


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    for book, path in INDEXES.items():
        chunks = json.loads(path.read_text(encoding="utf-8"))["chunks"]
        step = max(1, len(chunks) // want)
        print("=" * 78)
        print(book, len(chunks), "chunks")
        for index in range(want):
            chunk = chunks[min(index * step + step // 2, len(chunks) - 1)]
            text = " ".join(chunk["text"].split())[:700]
            print(f"\n[{book}] {chunk['chunk_id']}  heading={chunk.get('heading','')!r}")
            print(f"  chapter={chunk.get('chapter')}  section={chunk.get('section','')!r}")
            print("  " + text)


if __name__ == "__main__":
    main()
