"""Print the target passages for hand-authored wide-net questions.

Picks four chapters per book, spread through the book, and one deterministic
chunk from each. Read-only.

Run: python artifacts/probes/wide-net-targets-2026-10-23.py
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

INDEXES = [
    ("fde", ROOT / "data" / "index.json"),
    ("quantization", ROOT / "data" / "index.quantization.json"),
    ("ddia", ROOT / "data" / "index.ddia.json"),
]
SEED = "wide-net-hand-2026-10-23"
PER_BOOK = 4
# Spread positions through the numeric chapters: early, mid-early, mid-late, late.
POSITIONS = (0.20, 0.45, 0.75, 0.95)


def numeric_chapters(index):
    chapters = sorted({str(c.get("chapter")) for c in index.get("chunks") or []})
    return [c for c in chapters if c.isdigit()]


def pick(index, chapter):
    pool = [c for c in index.get("chunks") or []
            if str(c.get("chapter")) == chapter
            and 500 <= len((c.get("text") or "")) <= 1400
            and len((c.get("text") or "").split()) >= 70]
    pool.sort(key=lambda c: c["chunk_id"])
    if not pool:
        return None
    digest = hashlib.sha256(f"{SEED}:{chapter}".encode()).hexdigest()
    return pool[int(digest[:8], 16) % len(pool)]


def main():
    for book_id, path in INDEXES:
        index = json.loads(path.read_text(encoding="utf-8"))
        chapters = numeric_chapters(index)
        chosen = []
        for position in POSITIONS:
            chapter = chapters[min(len(chapters) - 1, int(position * len(chapters)))]
            if chapter not in chosen:
                chosen.append(chapter)
        print(f"\n{'=' * 78}\n{book_id}  chapters {chapters}")
        for chapter in chosen:
            chunk = pick(index, chapter)
            if chunk is None:
                print(f"\n-- ch{chapter}: no usable chunk")
                continue
            text = " ".join((chunk.get("text") or "").split())
            print(f"\n-- ch{chapter}  {chunk['chunk_id']}  [{chunk.get('heading') or ''}]")
            print(text[:900])


if __name__ == "__main__":
    main()
