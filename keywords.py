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

RARE_DF = 8
COVER_DF = 80


_POSTINGS_CACHE = {}


def postings(index):
    """word -> chunk positions, for every word of every chunk."""
    chunks = index.get("chunks") if isinstance(index, dict) else index
    chunks = chunks or []
    key = (id(chunks), len(chunks), chunks[0].get("chunk_id") if chunks and isinstance(chunks[0], dict) else None)
    if key in _POSTINGS_CACHE:
        return _POSTINGS_CACHE[key]

    table = {}
    for position, chunk in enumerate(chunks):
        text = chunk.get("text") if isinstance(chunk, dict) else str(chunk)
        for word in set(words(text)):
            table.setdefault(word, []).append(position)

    if len(_POSTINGS_CACHE) >= 16:
        try:
            _POSTINGS_CACHE.pop(next(iter(_POSTINGS_CACHE)))
        except Exception:
            _POSTINGS_CACHE.clear()
    _POSTINGS_CACHE[key] = table
    return table


def anchor_words(question, word_map, bound=COVER_DF):
    """Question words rare enough in the book to anchor a paragraph.

    "disadvantages" (df=4), "pitfalls" (df=3), "characteristics" (df=45)
    all qualify; function words and book-wide vocabulary do not. Stopwords
    are filtered before the count: their df says how the book talks, not
    what the question is about.
    """
    folded = {word for word in words(question) if word not in STOPWORDS}
    return {
        word for word in folded if 0 < len(word_map.get(word, ())) <= bound
    }


def rare(question, word_map, bound=None):
    """True when the question carries a word that lives in at most bound chunks.

    The caller uses this to decide whether the lexical channel joins at all;
    the band inside fusion decides whether it may reorder anything.
    """
    if bound is None:
        bound = RARE_DF
    folded = set(words(question))
    return any(0 < len(word_map.get(word, ())) <= bound for word in folded)
