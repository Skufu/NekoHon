"""Rare-word gate and paragraph anchors. Post-v1 retrieval work.

Gate: a question word living in at most RARE_DF chunks marks the question as
carrying rare vocabulary. The caller (answer.ask) uses this to decide whether
the lexical channel joins at all, via fusion.fuse. The band that decides
whether lexical evidence may reorder a passage lives in fusion.py; this
module no longer swaps anything.

Anchors: question words rare enough in the book (df <= COVER_DF) that
finding one in a paragraph makes it answering material. A fixed English
word list for list questions is not shippable (sampled list words range
from df=1 to df=77, no natural cutoff); the book's own counts are. Function
words are never anchors: the SMART stopword list (see preprocess.STOPWORDS)
filters them first, so a rare-in-book function word like "actually" cannot
trigger a paragraph expansion (stage 8 of preprocessing, wired 2026-10-13).
Stdlib only; no model, no download.
"""

from preprocess import STOPWORDS, words

from types import MappingProxyType

RARE_DF = 8
COVER_DF = 80


class _PostingPositions(tuple):
    """Immutable sequence of chunk positions, compatible with sequence equality checks."""

    def __eq__(self, other):
        if isinstance(other, list):
            return list(self) == other
        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)


_POSTINGS_CACHE = {}


def postings(index):
    """word -> chunk positions, for every word of every chunk."""
    if isinstance(index, dict) and "_postings" in index:
        cached = index["_postings"]
        if isinstance(cached, MappingProxyType):
            return cached
        table = {
            w: pos if isinstance(pos, tuple) else _PostingPositions(pos)
            for w, pos in cached.items()
        }
        proxy = MappingProxyType(table)
        index["_postings"] = proxy
        return proxy

    chunks = index.get("chunks") if isinstance(index, dict) else index
    chunks = chunks or []
    key = (id(chunks), len(chunks), chunks[0].get("chunk_id") if chunks and isinstance(chunks[0], dict) else None)
    if key in _POSTINGS_CACHE:
        cached = _POSTINGS_CACHE[key]
        if isinstance(index, dict) and "_postings" not in index:
            index["_postings"] = cached
        return cached

    raw_table = {}
    for position, chunk in enumerate(chunks):
        text = chunk.get("text") if isinstance(chunk, dict) else str(chunk)
        for word in set(words(text)):
            raw_table.setdefault(word, []).append(position)

    table = {word: _PostingPositions(pos) for word, pos in raw_table.items()}
    proxy = MappingProxyType(table)

    if len(_POSTINGS_CACHE) >= 16:
        try:
            _POSTINGS_CACHE.pop(next(iter(_POSTINGS_CACHE)))
        except Exception:
            _POSTINGS_CACHE.clear()
    _POSTINGS_CACHE[key] = proxy
    if isinstance(index, dict):
        index["_postings"] = proxy
    return proxy


def anchor_words(question, word_map, bound=COVER_DF):
    """Question words rare enough in the book to anchor a paragraph.

    "disadvantages" (df=4), "pitfalls" (df=3), "characteristics" (df=45)
    all qualify; function words and book-wide vocabulary do not. Stopwords
    are filtered before the count: their df says how the book talks, not
    what the question is about.
    """
    res = set()
    for word in words(question):
        if word not in STOPWORDS:
            pos = word_map.get(word)
            if pos and len(pos) <= bound:
                res.add(word)
    return res


def rare(question, word_map, bound=None):
    """True when the question carries a word that lives in at most bound chunks.

    The caller uses this to decide whether the lexical channel joins at all;
    the band inside fusion decides whether it may reorder anything.
    """
    if bound is None:
        bound = RARE_DF
    for word in set(words(question)):
        pos = word_map.get(word)
        if pos and len(pos) <= bound:
            return True
    return False
