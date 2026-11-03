#!/usr/bin/env python3
"""Report, and optionally pin, the generation kind of an index.

    python3 scripts/book-kind.py data/index.ddia.sqlite
    python3 scripts/book-kind.py data/index.<novel>.sqlite --set fiction

Without --set this reads the index and prints the dialogue numbers
bookkind.detect_kind uses plus the kind the engine would serve. With --set it
writes `kind` into the index metadata, which bookkind.for_index reads ahead of
the guess, so a book the guess gets wrong can be corrected without
re-ingesting it.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bookkind  # noqa: E402
import store  # noqa: E402

KINDS = bookkind.KINDS


def report(path):
    index = store.read_index(path)
    measured = bookkind.features(index)
    stored = index.get("kind")
    print(f"book     {index.get('book_id')}")
    print(f"title    {index.get('title')}")
    print(f"chunks   {measured['chunks']}")
    print(f"dialogue {measured['dialogue_ratio']:.4f} (line {bookkind.FICTION_DIALOGUE_RATIO})")
    print(f"share    {measured['dialogue_chunk_share']:.3f} (line {bookkind.FICTION_DIALOGUE_CHUNK_SHARE})")
    print(f"stored   {stored or '-'}")
    print(f"kind     {bookkind.kind(index)}")
    return index


def pin(path, kind):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('kind', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(kind),),
        )
    print(f"stored   {kind}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("index", help="Path to an index database")
    parser.add_argument(
        "--set", dest="kind", choices=KINDS,
        help="Pin this kind in the index metadata",
    )
    args = parser.parse_args()

    path = Path(args.index)
    if not path.is_file():
        raise SystemExit(f"no index at {path}")
    report(path)
    if args.kind:
        pin(path, args.kind)
        report(path)


if __name__ == "__main__":
    main()
