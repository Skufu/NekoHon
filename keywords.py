"""Rare-word gate and paragraph anchors. Post-v1 retrieval work.

Gate: a question word living in at most RARE_DF chunks marks the question as
carrying rare vocabulary. The caller (answer.ask) uses this to decide whether
the lexical channel joins at all, via fusion.fuse. The band that decides
whether lexical evidence may reorder a passage lives in fusion.py; this
module no longer swaps anything.

Anchors: question words rare enough in the book (df <= COVER_DF) that
finding one in a paragraph makes it answering material. A fixed English
word list for list questions is not shippable (sampled list words range
from df=1 to df=77, no natural cutoff); the book's own counts are.
Stdlib only; no model, no download.
"""

from preprocess import words

RARE_DF = 8
COVER_DF = 80


def postings(index):
    """word -> chunk positions, for every word of every chunk."""
    table = {}
    for position, chunk in enumerate(index.get("chunks") or []):
        for word in set(words(chunk.get("text"))):
            table.setdefault(word, []).append(position)
    return table


def anchor_words(question, word_map, bound=COVER_DF):
    """Question words rare enough in the book to anchor a paragraph.

    "disadvantages" (df=4), "pitfalls" (df=3), "characteristics" (df=45)
    all qualify; function words and book-wide vocabulary do not.
    """
    folded = set(words(question))
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
