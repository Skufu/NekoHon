"""SQLite storage for book indexes, including the FTS5 tables.

The engine keeps its in-memory dict shape (``{"book_id": ..., "chunks": [...],
"figures": [...]}``) so retrieval, answer logic, and harnesses need no rewrite.
This module is the durable side: one database per book, atomic writes, and the
same two FTS5 virtual tables ``fts_index`` queries.

Schema version 1:

- ``meta``: one JSON value per top-level index key except ``chunks``/``figures``.
- ``chunks``: explicit columns for every field the engine reads; anything else
  travels in ``extra`` so no record loses a key.
- ``figures``: same treatment with ``id`` as ``figure_id``.
- ``chunks_fts``: porter unicode61 over (heading, section, body); rowid is the
  chunk position.
- ``chunks_trigram``: trigram over one body string; rowid is the chunk position.

Embeddings are little-endian float64 blobs. The JSON indexes stored Python
floats; double keeps every stored value exact, and the dense ranker still
builds its hot-path matrix in float32.

Writes go to a sibling ``.tmp`` database and replace the target with
``os.replace`` only after a successful commit, so a crash leaves the previous
index intact. Reads open ``mode=ro``; the file is never mutated by a reader.

CLI:
    python store.py --migrate data/index.json [data/index.ddia.json ...]
    python store.py --verify data/index.json data/index.sqlite
    python store.py --check data/index.sqlite [data/index.ddia.sqlite ...]
"""

import argparse
import json
import os
import sqlite3
import struct
import tempfile
from pathlib import Path

SCHEMA_VERSION = 1
DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")

SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE chunks (
    position INTEGER PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    chapter,
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    section TEXT,
    doc TEXT,
    anchor TEXT,
    blocks TEXT,
    figures TEXT,
    embedding BLOB,
    embedding_input_sha256 TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE figures (
    position INTEGER PRIMARY KEY,
    figure_id TEXT NOT NULL UNIQUE,
    chapter,
    caption TEXT,
    referencing_paragraph TEXT,
    file TEXT,
    anchor TEXT,
    source TEXT,
    embedding BLOB,
    embedding_input_sha256 TEXT,
    extra TEXT NOT NULL DEFAULT '{}'
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    heading, section, body, tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE chunks_trigram USING fts5(
    body, tokenize='trigram'
);
"""

CHUNK_COLUMNS = (
    "chunk_id", "chapter", "heading", "text", "source", "section", "doc",
    "anchor", "blocks", "figures",
)
FIGURE_COLUMNS = (
    "figure_id", "chapter", "caption", "referencing_paragraph", "file",
    "anchor", "source",
)
JSON_COLUMNS = {"blocks", "figures"}


def is_index_db(path):
    """True when the path names a supported SQLite database file."""
    return Path(path).suffix.lower() in DB_SUFFIXES


def _pack_embedding(vector):
    if not vector:
        return None
    return struct.pack(f"<{len(vector)}d", *vector)


def _unpack_embedding(blob):
    if not blob:
        return None
    return list(struct.unpack(f"<{len(blob) // 8}d", blob))


def _split_record(record, known):
    row = {}
    extra = {}
    for key, value in record.items():
        if key.startswith("_") or key in ("embedding", "embedding_input_sha256"):
            continue
        if key in known:
            row[key] = value
        else:
            extra[key] = value
    return row, extra


def _insert_chunks(cur, chunks):
    for position, chunk in enumerate(chunks):
        row, extra = _split_record(chunk, CHUNK_COLUMNS)
        values = [
            row.get("chunk_id", ""),
            row.get("chapter"),
            row.get("heading") or "",
            row.get("text") or "",
            row.get("source") or "",
            row.get("section"),
            row.get("doc"),
            row.get("anchor"),
            json.dumps(row.get("blocks")) if "blocks" in row else None,
            json.dumps(row.get("figures")) if "figures" in row else None,
            _pack_embedding(chunk.get("embedding")),
            chunk.get("embedding_input_sha256"),
            json.dumps(extra),
        ]
        cur.execute(
            "INSERT INTO chunks (position, chunk_id, chapter, heading, text, "
            "source, section, doc, anchor, blocks, figures, embedding, "
            "embedding_input_sha256, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?)",
            [position, *values],
        )
        heading = (chunk.get("heading") or "").strip()
        section = (chunk.get("section") or "").strip()
        body = (chunk.get("text") or "").strip()
        cur.execute(
            "INSERT INTO chunks_fts (rowid, heading, section, body) VALUES (?, ?, ?, ?)",
            (position, heading, section, body),
        )
        cur.execute(
            "INSERT INTO chunks_trigram (rowid, body) VALUES (?, ?)",
            (position, f"{heading}\n{section}\n{body}".strip()),
        )


def _insert_figures(cur, figures):
    for position, figure in enumerate(figures):
        row, extra = _split_record(figure, FIGURE_COLUMNS + ("id",))
        values = [
            row.get("figure_id") or row.get("id") or "",
            row.get("chapter"),
            row.get("caption"),
            row.get("referencing_paragraph"),
            row.get("file"),
            row.get("anchor"),
            row.get("source"),
            _pack_embedding(figure.get("embedding")),
            figure.get("embedding_input_sha256"),
            json.dumps(extra),
        ]
        cur.execute(
            "INSERT INTO figures (position, figure_id, chapter, caption, "
            "referencing_paragraph, file, anchor, source, embedding, "
            "embedding_input_sha256, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?)",
            [position, *values],
        )


def write_index(path, index):
    """Write the index dict to a SQLite database, replacing atomically."""
    if not isinstance(index, dict):
        raise TypeError("index must be a dict")
    target = Path(path).resolve()
    if not is_index_db(target):
        raise ValueError(
            f"index storage must use one of {DB_SUFFIXES}, not {target.suffix or '<none>'}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    tmp = Path(tmp_name)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        cur = conn.cursor()
        meta = {
            "schema_version": SCHEMA_VERSION,
        }
        for key, value in index.items():
            if key.startswith("_") or key in ("chunks", "figures"):
                continue
            meta[key] = value
        for key, value in meta.items():
            cur.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        _insert_chunks(cur, index.get("chunks") or [])
        _insert_figures(cur, index.get("figures") or [])
        conn.commit()
    except Exception:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp, target)
    return target


def _row_to_chunk(row):
    (
        chunk_id, chapter, heading, text, source, section, doc, anchor,
        blocks, figures, embedding, embedding_input_sha256, extra,
    ) = row
    record = {"chunk_id": chunk_id}
    if chapter is not None:
        record["chapter"] = chapter
    record["heading"] = heading or ""
    record["text"] = text or ""
    record["source"] = source or ""
    if section is not None:
        record["section"] = section
    if doc is not None:
        record["doc"] = doc
    if anchor is not None:
        record["anchor"] = anchor
    if blocks is not None:
        record["blocks"] = json.loads(blocks)
    if figures is not None:
        record["figures"] = json.loads(figures)
    vector = _unpack_embedding(embedding)
    if vector is not None:
        record["embedding"] = vector
    if embedding_input_sha256:
        record["embedding_input_sha256"] = embedding_input_sha256
    record.update(json.loads(extra or "{}"))
    return record


def _row_to_figure(row):
    (
        figure_id, chapter, caption, referencing_paragraph, file, anchor,
        source, embedding, embedding_input_sha256, extra,
    ) = row
    record = {"id": figure_id}
    if chapter is not None:
        record["chapter"] = chapter
    if caption is not None:
        record["caption"] = caption
    if referencing_paragraph is not None:
        record["referencing_paragraph"] = referencing_paragraph
    if file is not None:
        record["file"] = file
    if anchor is not None:
        record["anchor"] = anchor
    if source is not None:
        record["source"] = source
    vector = _unpack_embedding(embedding)
    if vector is not None:
        record["embedding"] = vector
    if embedding_input_sha256:
        record["embedding_input_sha256"] = embedding_input_sha256
    record.update(json.loads(extra or "{}"))
    return record


def open_readonly(path):
    """A read-only connection; the file is never created or mutated."""
    resolved = Path(path).resolve()
    uri = resolved.as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, check_same_thread=False)


def read_index(path):
    """Load a SQLite index back into the engine's dict shape."""
    resolved = Path(path).resolve()
    conn = open_readonly(resolved)
    try:
        cur = conn.cursor()
        meta = dict(cur.execute("SELECT key, value FROM meta").fetchall())
        version = json.loads(meta.pop("schema_version", "null"))
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"{resolved.name}: schema version {version!r}, expected {SCHEMA_VERSION}"
            )
        index = {key: json.loads(value) for key, value in meta.items()}
        index["chunks"] = [
            _row_to_chunk(row)
            for row in cur.execute(
                "SELECT chunk_id, chapter, heading, text, source, section, doc, "
                "anchor, blocks, figures, embedding, embedding_input_sha256, extra "
                "FROM chunks ORDER BY position"
            )
        ]
        index["figures"] = [
            _row_to_figure(row)
            for row in cur.execute(
                "SELECT figure_id, chapter, caption, referencing_paragraph, file, "
                "anchor, source, embedding, embedding_input_sha256, extra "
                "FROM figures ORDER BY position"
            )
        ]
        return index
    finally:
        conn.close()


def check_database(path):
    """Storage-level issues: SQLite integrity, schema version, FTS row counts.

    Returns human-readable strings; empty means the database is structurally
    sound. This is the half `read_index` cannot see: a truncated or missing FTS
    table still decodes every chunk, but the lexical channel would silently
    return nothing.
    """
    resolved = Path(path).resolve()
    issues = []
    try:
        conn = open_readonly(resolved)
    except sqlite3.Error as exc:
        return [f"cannot open {resolved.name}: {exc}"]
    try:
        cur = conn.cursor()
        try:
            quick = cur.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.Error as exc:
            issues.append(f"quick_check failed: {exc}")
            quick = None
        if quick not in (None, "ok"):
            issues.append(f"quick_check: {quick}")
        try:
            version = cur.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.Error as exc:
            return issues + [f"missing meta table: {exc}"]
        version_value = json.loads(version[0]) if version else None
        if version_value != SCHEMA_VERSION:
            issues.append(
                f"schema version {version_value!r}, expected {SCHEMA_VERSION}"
            )
        try:
            chunk_count = cur.execute("SELECT count(*) FROM chunks").fetchone()[0]
        except sqlite3.Error as exc:
            return issues + [f"missing chunks table: {exc}"]
        for table in ("chunks_fts", "chunks_trigram"):
            try:
                count = cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error as exc:
                issues.append(f"missing {table}: {exc}")
                continue
            if count != chunk_count:
                issues.append(f"{table} rows {count} != chunks {chunk_count}")
    finally:
        conn.close()
    return issues


def _same_value(left, right):
    if isinstance(left, float) or isinstance(right, float):
        try:
            return abs(float(left) - float(right)) <= 1e-6
        except (TypeError, ValueError):
            return left == right
    return left == right


def compare_indexes(json_index, db_index, limit=5):
    """Differences between a JSON index and its SQLite twin.

    Returns a list of human-readable strings; empty means equivalent at the
    engine's precision. Embeddings compare at 1e-6 absolute tolerance, which is
    the rounding the JSON store already applied.
    """
    problems = []
    for key in sorted(set(json_index) | set(db_index)):
        if key in ("chunks", "figures"):
            continue
        if not _same_value(json_index.get(key), db_index.get(key)):
            problems.append(f"meta {key}: {json_index.get(key)!r} != {db_index.get(key)!r}")
    for kind in ("chunks", "figures"):
        left = json_index.get(kind) or []
        right = db_index.get(kind) or []
        if len(left) != len(right):
            problems.append(f"{kind}: {len(left)} rows != {len(right)} rows")
            continue
        for position, (a, b) in enumerate(zip(left, right)):
            for key in sorted(set(a) | set(b)):
                va, vb = a.get(key), b.get(key)
                if key == "embedding":
                    if va is None or vb is None:
                        if va is not vb:
                            problems.append(f"{kind}[{position}].embedding presence differs")
                        continue
                    if len(va) != len(vb):
                        problems.append(
                            f"{kind}[{position}].embedding width {len(va)} != {len(vb)}"
                        )
                        continue
                    worst = max((abs(x - y) for x, y in zip(va, vb)), default=0.0)
                    if worst > 1e-6:
                        problems.append(
                            f"{kind}[{position}].embedding differs by {worst:.3g}"
                        )
                    continue
                if not _same_value(va, vb):
                    problems.append(f"{kind}[{position}].{key}: {va!r} != {vb!r}")
                if len(problems) >= limit:
                    return problems
    return problems


def _migrate_one(source, destination=None):
    source = Path(source)
    if not source.is_file():
        raise SystemExit(f"missing JSON index: {source}")
    destination = Path(destination) if destination else source.with_suffix(".sqlite")
    index = json.loads(source.read_text(encoding="utf-8"))
    write_index(destination, index)
    problems = compare_indexes(index, read_index(destination))
    if problems:
        raise SystemExit(
            f"{source.name} -> {destination.name} mismatch:\n  "
            + "\n  ".join(problems)
        )
    print(f"{source} -> {destination} ({destination.stat().st_size} bytes)")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--migrate", nargs="+", metavar="JSON", help="Convert JSON indexes to SQLite")
    parser.add_argument("--verify", nargs=2, metavar=("JSON", "DB"), help="Compare a JSON index with a database")
    parser.add_argument("--check", nargs="+", metavar="DB", help="Run SQLite integrity and FTS row checks")
    args = parser.parse_args()
    if args.migrate:
        for source in args.migrate:
            _migrate_one(source)
    elif args.check:
        failed = False
        for destination in args.check:
            issues = check_database(destination)
            print(f"{destination}: {'clean' if not issues else '; '.join(issues)}")
            failed = failed or bool(issues)
        raise SystemExit(1 if failed else 0)
    elif args.verify:
        source, destination = args.verify
        problems = compare_indexes(
            json.loads(Path(source).read_text(encoding="utf-8")),
            read_index(destination),
        )
        if problems:
            print("\n".join(problems))
            raise SystemExit(1)
        print("equivalent")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
