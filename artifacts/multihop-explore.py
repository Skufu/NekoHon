"""Exploration helper for the multi-hop hunt: grep chunk texts for evidence.

Read-only over data/index.json. One section per argv pattern; shows up to
`--max` matching chunks per pattern with a context window around the match.

Run: python artifacts/multihop-explore.py "pattern one" "pattern two"
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WINDOW_BEFORE = 60
WINDOW_AFTER = 160
MAX_PER_PATTERN = 8


def main():
    args = sys.argv[1:]
    chapter = None
    if "--chapter" in args:
        position = args.index("--chapter")
        chapter = args[position + 1]
        del args[position:position + 2]
    index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
    chunks = index.get("chunks") or []
    if chapter is not None:
        chunks = [c for c in chunks if str(c.get("chapter")) == chapter]
    if args and args[0] == "--reach":
        sys.path.insert(0, str(ROOT))
        from agentic import build_tools

        query = args[1]
        targets = args[2:]
        state = {"word_map": None}
        print(f"reach for query: {query!r} (targets: {', '.join(targets)})")
        for name, tool in build_tools().items():
            hits = tool.search(query, index, state)
            ids = [hit["chunk_id"] for hit in hits]
            ranks = {t: (ids.index(t) + 1 if t in ids else None) for t in targets}
            print(f"  {name:8} top: {', '.join(ids)}")
            print(f"           target ranks: {ranks}")
        return
    if args and args[0] == "--show":
        by_id = {c["chunk_id"]: c for c in chunks}
        for chunk_id in args[1:]:
            chunk = by_id.get(chunk_id)
            if chunk is None:
                print(f"{chunk_id}: not found")
                continue
            text = " ".join((chunk.get("text") or "").split())
            print(f"--- {chunk_id} ch{chunk['chapter']} ---")
            print(text)
            print()
        return
    if not args:
        raise SystemExit("usage: multihop-explore.py <pattern> [pattern ...] | --show <chunk_id> ...")
    print(f"index: {len(chunks)} chunks, embedder {index.get('embedder')}")
    for arg in args:
        pattern = re.compile(arg, re.I)
        print("=" * 78)
        print(f"pattern: {arg}" + (f" (chapter {chapter})" if chapter else ""))
        shown = 0
        for chunk in chunks:
            text = " ".join((chunk.get("text") or "").split())
            match = pattern.search(text)
            if not match:
                continue
            start = max(0, match.start() - WINDOW_BEFORE)
            end = min(len(text), match.end() + WINDOW_AFTER)
            print(f'  {chunk["chunk_id"]:9} ch{chunk["chapter"]:>6}  ...{text[start:end]}...')
            shown += 1
            if shown >= MAX_PER_PATTERN:
                rest = sum(
                    1 for c in chunks if pattern.search(" ".join((c.get("text") or "").split()))
                ) - shown
                if rest > 0:
                    print(f"  ... and {rest} more chunk(s)")
                break
        if shown == 0:
            print("  no matches")


if __name__ == "__main__":
    main()
