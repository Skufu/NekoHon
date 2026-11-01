"""SQLite FTS5 full-text and trigram indexing for book chunks.

Provides:
- chunks_fts (porter unicode61): BM25 ranking weighting heading 2.0, body 1.0.
- chunks_trigram (trigram): exact symbol, code identifier, substring lookup.

Lifecycle (2026-10-31). One SQLite connection is cached per index dict, and a
process-wide re-entrant lock serializes every access to it. An index loaded by
``store.read_index`` carries ``_db_path``; its persisted FTS tables are opened
read-only, so a process pays no build cost and holds no second copy of the
tables. Dict-only indexes (tests, a freshly ingested book before it is saved)
build one in-memory copy per loaded index. ``server.py`` runs a
``ThreadingHTTPServer``, so a connection built by the first request thread is
later used by other threads; it is opened with ``check_same_thread=False`` and
the lock - not the flag - is what makes that safe: no statement runs on the
shared connection from two threads at once.

The in-memory cache is keyed by a content fingerprint over each chunk's
(source, heading, text), not by chunk count alone, so an equal-count text edit
rebuilds the tables; a persisted connection is keyed by the database file's
mtime and size. The replaced connection is closed on rebuild.
``close_fts_connection`` drops the cache explicitly for a caller that replaces
or unloads an index.

Build and query failures raise ``FtsUnavailable``. The fusion caller catches it,
logs a warning, marks the backend in the request trace, and falls back to the
legacy idf channel; a caller that asks for scores directly gets the error rather
than an empty result that would look like "no match".
"""

import sqlite3
import threading
import weakref
from pathlib import Path

from preprocess import tokens

# Serializes cache checks, rebuilds, queries, and closes. Held only around the
# (sub-millisecond) FTS work, never around embedding or generation. An RLock so
# query helpers can re-enter through get_fts_connection.
_FTS_LOCK = threading.RLock()


class FtsUnavailable(RuntimeError):
    """FTS5 is unavailable, or its SQLite connection failed."""


class _FtsHandle:
    """Cached connection plus the identity of the chunks it was built from."""

    __slots__ = ("conn", "fingerprint", "chunk_count", "db_path", "__weakref__")

    def __init__(self, conn, fingerprint, chunk_count, db_path):
        self.conn = conn
        self.fingerprint = fingerprint
        self.chunk_count = chunk_count
        self.db_path = db_path


def _close_quietly(conn):
    try:
        conn.close()
    except Exception:
        # A double close during shutdown must not mask the original path.
        pass


def _content_fingerprint(chunks):
    """Content identity of the indexed material, in chunk order.

    Python caches a string's hash on the string object, so after the first call
    the per-query cost is O(chunks) integer work, not O(bytes); the first call
    hashes the text once (about 1 ms for a 1 MB book). Chunk ids are excluded:
    rowid is the position, and (source, heading, text) is the material the FTS
    tables actually serve.
    """
    digest = 0
    for chunk in chunks:
        digest = hash(
            (
                digest,
                chunk.get("source") or "",
                chunk.get("heading") or "",
                chunk.get("section") or "",
                chunk.get("text") or "",
            )
        )
    return digest


def _build_connection(chunks, db_path):
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
    except sqlite3.Error as exc:
        raise FtsUnavailable(f"cannot open FTS database {db_path!r}: {exc}") from exc
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
            "heading, section, body, tokenize='porter unicode61')"
        )
        cur.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_trigram USING fts5("
            "body, tokenize='trigram')"
        )
        for pos, chunk in enumerate(chunks):
            heading = (chunk.get("heading") or "").strip()
            section = (chunk.get("section") or "").strip()
            body = (chunk.get("text") or "").strip()
            cur.execute(
                "INSERT INTO chunks_fts(rowid, heading, section, body) VALUES (?, ?, ?, ?)",
                (pos, heading, section, body),
            )
            cur.execute(
                "INSERT INTO chunks_trigram(rowid, body) VALUES (?, ?)",
                (pos, f"{heading}\n{section}\n{body}".strip()),
            )
        conn.commit()
    except sqlite3.Error as exc:
        _close_quietly(conn)
        raise FtsUnavailable(
            f"cannot build FTS5 index for {len(chunks)} chunks: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return conn


def _db_fingerprint(path):
    stat = Path(path).stat()
    return ("db", stat.st_mtime_ns, stat.st_size)


def _open_db_connection(path):
    import store

    try:
        conn = store.open_readonly(path)
        cur = conn.cursor()
        tables = {
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('chunks_fts', 'chunks_trigram')"
            )
        }
        missing = {"chunks_fts", "chunks_trigram"} - tables
        if missing:
            _close_quietly(conn)
            raise FtsUnavailable(
                f"database {path!r} is missing FTS tables: {sorted(missing)}"
            )
    except sqlite3.Error as exc:
        raise FtsUnavailable(f"cannot open FTS database {path!r}: {exc}") from exc
    return conn


def _handle_locked(index, db_path=":memory:"):
    """Cached handle for this index, rebuilt when its material changed.

    A loaded SQLite index carries ``_db_path``; its persisted FTS tables are
    opened read-only instead of rebuilding an in-memory copy. Dict-only indexes
    (tests, migration) still build in memory.

    The caller must hold ``_FTS_LOCK``.
    """
    if not isinstance(index, dict):
        return None
    chunks = index.get("chunks") or []
    source_db = index.get("_db_path") if db_path == ":memory:" else None
    cached = index.get("_fts_conn")
    handle = cached if isinstance(cached, _FtsHandle) else None
    if source_db and Path(source_db).is_file():
        try:
            fingerprint = _db_fingerprint(source_db)
        except OSError:
            source_db = None
        else:
            if (
                handle is not None
                and handle.fingerprint == fingerprint
                and handle.chunk_count == len(chunks)
                and handle.db_path == source_db
            ):
                return handle
            conn = _open_db_connection(source_db)
            new_handle = _FtsHandle(conn, fingerprint, len(chunks), source_db)
            index["_fts_conn"] = new_handle
            index["_fts_chunk_count"] = len(chunks)
            weakref.finalize(new_handle, _close_quietly, conn)
            if handle is not None:
                _close_quietly(handle.conn)
            elif isinstance(cached, sqlite3.Connection):
                _close_quietly(cached)
            return new_handle

    fingerprint = _content_fingerprint(chunks)
    if (
        handle is not None
        and handle.fingerprint == fingerprint
        and handle.chunk_count == len(chunks)
        and handle.db_path == db_path
    ):
        return handle

    conn = _build_connection(chunks, db_path)
    new_handle = _FtsHandle(conn, fingerprint, len(chunks), db_path)
    index["_fts_conn"] = new_handle
    index["_fts_chunk_count"] = len(chunks)
    # Tie cleanup to the handle so replacing the whole index dict (server
    # reload) releases its in-memory tables instead of waiting for process end.
    weakref.finalize(new_handle, _close_quietly, conn)
    if handle is not None:
        _close_quietly(handle.conn)
    elif isinstance(cached, sqlite3.Connection):
        # A raw connection cached by pre-handle code or a caller.
        _close_quietly(cached)
    return new_handle


def get_fts_connection(index, db_path=":memory:"):
    """Get or build the cached SQLite FTS5 connection for this index.

    The connection is shared across request threads and opened with
    ``check_same_thread=False``. The retrieval helpers serialize access with
    ``_FTS_LOCK``; direct callers that run SQL concurrently must not assume
    more than SQLite's own connection-level serialization. A later content
    change rebuilds and closes this connection; do not hold it across an
    index change.
    """
    with _FTS_LOCK:
        handle = _handle_locked(index, db_path)
        return handle.conn if handle is not None else None


def close_fts_connection(index):
    """Close and forget the cached FTS connection. True when one existed."""
    if not isinstance(index, dict):
        return False
    with _FTS_LOCK:
        cached = index.pop("_fts_conn", None)
        index.pop("_fts_chunk_count", None)
        conn = cached.conn if isinstance(cached, _FtsHandle) else cached
        if isinstance(conn, sqlite3.Connection):
            _close_quietly(conn)
            return True
    return False


def _escape_fts5_token(token):
    """Enclose token in double quotes, escaping any inner double quotes."""
    return '"' + token.replace('"', '""') + '"'


def fts_bm25_scores(index, question, ranks=None, band=None):
    """chunk_position -> positive BM25 score, restricted to admissible ranks.

    Weighting: heading 2.0, body 1.0.
    Queries use OR across candidate content terms (terms present in more than
    half the corpus are dropped to prevent common-word noise).
    """
    chunks = (index.get("chunks") or []) if isinstance(index, dict) else []
    if not chunks or not question:
        return {}

    query_tokens = tokens(question)
    if not query_tokens:
        return {}

    total = len(chunks)
    with _FTS_LOCK:
        handle = _handle_locked(index)
        if handle is None:
            return {}
        conn = handle.conn
        try:
            cur = conn.cursor()
            admissible_tokens = []
            for tok in set(query_tokens):
                esc = _escape_fts5_token(tok)
                cur.execute(
                    "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
                    (esc,),
                )
                cnt = cur.fetchone()[0]
                if 0 < cnt <= total / 2:
                    admissible_tokens.append(tok)

            if not admissible_tokens:
                return {}

            match_expr = " OR ".join(
                _escape_fts5_token(t) for t in admissible_tokens
            )
            cur.execute(
                "SELECT rowid, -bm25(chunks_fts, 2.0, 1.5, 1.0) AS score "
                "FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY score DESC",
                (match_expr,),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise FtsUnavailable(
                f"FTS5 query failed: {type(exc).__name__}: {exc}"
            ) from exc

        scores = {}
        for pos, score in rows:
            if not (0 <= pos < len(chunks)):
                continue
            pos_score = float(score)
            if pos_score <= 0.0:
                continue
            if ranks is not None and band is not None:
                chunk_id = chunks[pos].get("chunk_id")
                rank = ranks.get(chunk_id)
                if not rank or rank > band:
                    continue
            scores[pos] = pos_score

    return scores


def search_trigram(index, term):
    """Exact symbol, code identifier, or substring lookup via trigram index."""
    if not term:
        return []
    chunks = (index.get("chunks") or []) if isinstance(index, dict) else []
    if not chunks:
        return []
    esc = '"' + term.replace('"', '""') + '"'
    with _FTS_LOCK:
        handle = _handle_locked(index)
        if handle is None:
            return []
        try:
            cur = handle.conn.cursor()
            cur.execute(
                "SELECT rowid FROM chunks_trigram WHERE chunks_trigram MATCH ?",
                (esc,),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise FtsUnavailable(
                f"FTS5 trigram query failed: {type(exc).__name__}: {exc}"
            ) from exc
        return [chunks[r[0]] for r in rows if 0 <= r[0] < len(chunks)]
