"""SQLite FTS5 full-text and trigram indexing for book chunks.

Provides:
- chunks_fts (porter unicode61): BM25 ranking weighting heading 2.0, body 1.0.
- chunks_trigram (trigram): exact symbol, code identifier, substring lookup.
"""

import os
import re
import sqlite3
from preprocess import tokens


def get_fts_connection(index, db_path=":memory:"):
    """Get or build the cached SQLite FTS5 connection for this index."""
    if not isinstance(index, dict):
        return None
    conn = index.get("_fts_conn")
    chunks = index.get("chunks") or []
    if conn is not None and index.get("_fts_chunk_count") == len(chunks):
        return conn

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
        "heading, body, tokenize='porter unicode61')"
    )
    cur.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_trigram USING fts5("
        "body, tokenize='trigram')"
    )

    for pos, chunk in enumerate(chunks):
        heading = (chunk.get("heading") or "").strip()
        body = (chunk.get("text") or "").strip()
        cur.execute(
            "INSERT INTO chunks_fts(rowid, heading, body) VALUES (?, ?, ?)",
            (pos, heading, body),
        )
        cur.execute(
            "INSERT INTO chunks_trigram(rowid, body) VALUES (?, ?)",
            (pos, f"{heading}\n{body}".strip()),
        )
    conn.commit()
    index["_fts_conn"] = conn
    index["_fts_chunk_count"] = len(chunks)
    return conn


def _escape_fts5_token(token):
    """Enclose token in double quotes, escaping any inner double quotes."""
    return '"' + token.replace('"', '""') + '"'


def fts_bm25_scores(index, question, ranks=None, band=None):
    """chunk_position -> positive BM25 score, restricted to admissible ranks.

    Weighting: heading 2.0, body 1.0.
    Queries use OR across candidate content terms (excluding stopwords / terms
    present in > half the corpus to prevent common-word noise).
    """
    chunks = index.get("chunks") or []
    if not chunks or not question:
        return {}

    conn = get_fts_connection(index)
    if conn is None:
        return {}

    total = len(chunks)
    query_tokens = tokens(question)
    if not query_tokens:
        return {}

    cur = conn.cursor()
    admissible_tokens = []
    for tok in set(query_tokens):
        esc = _escape_fts5_token(tok)
        try:
            cur.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", (esc,))
            cnt = cur.fetchone()[0]
            if 0 < cnt <= total / 2:
                admissible_tokens.append(tok)
        except sqlite3.OperationalError:
            continue

    if not admissible_tokens:
        return {}

    match_expr = " OR ".join(_escape_fts5_token(t) for t in admissible_tokens)
    scores = {}
    try:
        cur.execute(
            "SELECT rowid, -bm25(chunks_fts, 2.0, 1.0) AS score "
            "FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY score DESC",
            (match_expr,),
        )
        rows = cur.fetchall()
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
    except sqlite3.OperationalError:
        return {}

    return scores


def search_trigram(index, term):
    """Exact symbol, code identifier, or substring lookup via trigram index."""
    if not term:
        return []
    chunks = index.get("chunks") or []
    if not chunks:
        return []
    conn = get_fts_connection(index)
    if conn is None:
        return []
    esc = '"' + term.replace('"', '""') + '"'
    try:
        cur = conn.cursor()
        cur.execute("SELECT rowid FROM chunks_trigram WHERE chunks_trigram MATCH ?", (esc,))
        rows = cur.fetchall()
        return [chunks[r[0]] for r in rows if 0 <= r[0] < len(chunks)]
    except sqlite3.OperationalError:
        return []
