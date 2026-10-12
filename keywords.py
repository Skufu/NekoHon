"""Rare-word lexical boost and paragraph anchors. Post-v1 retrieval work.

Boost: if the question carries a rare word that exists in the book
(df <= RARE_DF), score every chunk by idf-weighted overlap with the
question's words and swap the best-overlap chunk in for the last (weakest)
dense passage. A passage already present is never duplicated or displaced.

RARE_DF decides only how eager the channel is. Safety is the dense band: the
chunk to be promoted must sit inside the dense top RANK_BAND of the corpus,
or nothing is injected. Measured 2026-10-12:
- "what does data engineers need to be pragmatic about" promotes ch04-012,
  dense rank 51 of 1065 (4.8%),
- "MAD data landscape" promotes ch04-019, rank 140 (13.1%) — and ch04-019's
  presence is what makes the model quote the MAD sentence out of ch04-020,
- "multicloud methodology disadvantages" promotes ch04-038, rank 1,
- "What is the capital of France?" would promote ch02-068 at rank 695 (65%),
  so the band refuses it. The refusal stands even with RARE_DF raised, so it
  no longer rests on this book's df for "capital".
The band first stood at 0.10, which silently dropped the MAD case (13.1%) and
with it the MAD sentence: what the model is handed changed under it. 0.20
admits every measured legitimate anchor and still refuses France by more than
3x, so the safe range is 13.1% to 65%. Recorded because moving a constant is a
judgment, not a fit: the band exists to exclude the tail, and 13.1% is not the
tail. Do not move it again without a case outside that range.

Anchors: question words rare enough in the book (df <= COVER_DF) that
finding one in a paragraph makes it answering material. A fixed English
word list for list questions is not shippable (sampled list words range
from df=1 to df=77, no natural cutoff); the book's own counts are.
Stdlib only; no model, no download.
"""

import math
import re

WORD = re.compile(r"[A-Za-z]+")
RARE_DF = 8
COVER_DF = 80
# A promoted chunk must sit in the dense top RANK_BAND of the corpus. Dimensionless
# on purpose: an absolute count would mean a different thing on a bigger book.
RANK_BAND = 0.20


def postings(index):
    """word -> chunk positions, for every word of every chunk."""
    table = {}
    for position, chunk in enumerate(index.get("chunks") or []):
        words = {m.group().lower() for m in WORD.finditer(chunk.get("text") or "")}
        for word in words:
            table.setdefault(word, []).append(position)
    return table


def anchor_words(question, word_map, bound=COVER_DF):
    """Question words rare enough in the book to anchor a paragraph.

    "disadvantages" (df=4), "pitfalls" (df=3), "characteristics" (df=45)
    all qualify; function words and book-wide vocabulary do not.
    """
    words = {m.group().lower() for m in WORD.finditer(question or "")}
    return {
        word for word in words if 0 < len(word_map.get(word, ())) <= bound
    }


def rare(question, word_map, bound=None):
    """True when the question carries a word that lives in at most bound chunks.

    The caller uses this to decide whether the dense rank map is worth paying
    for. What actually decides an injection is the band in boost.
    """
    if bound is None:
        bound = RARE_DF
    words = {m.group().lower() for m in WORD.finditer(question or "")}
    return any(0 < len(word_map.get(word, ())) <= bound for word in words)


def _plausible(chunk, rank_map, total):
    """True when the dense model already ranks the chunk near the top.

    No rank map is no evidence, and no evidence fails closed: the France
    refusal depends on this, not on RARE_DF.
    """
    if not rank_map:
        return False
    rank = rank_map.get(chunk.get("chunk_id"))
    if not rank:
        return False
    return rank <= max(1, round(RANK_BAND * total))


def boost(index, question, passages, word_map=None, rank_map=None):
    """The passages with the best-overlap chunk swapped in, or unchanged.

    Only fires when the question contains a rare book word; never injects a
    passage that is already present; replaces only the last passage. The
    promoted chunk must pass the dense band, so the lexical channel can
    reorder what dense search already considered, never smuggle in a passage
    from the tail.
    """
    chunks = index.get("chunks") or []
    if not chunks or not passages:
        return passages
    word_map = word_map or postings(index)
    total = len(chunks)
    if not rare(question, word_map):
        return passages
    words = {m.group().lower() for m in WORD.finditer(question)}
    scores = {}
    for word in words:
        positions = word_map.get(word)
        if not positions or len(positions) > total / 2:
            continue
        weight = math.log((total - len(positions) + 0.5) / (len(positions) + 0.5))
        if weight <= 0:
            continue
        for position in positions:
            scores[position] = scores.get(position, 0.0) + weight
    if not scores:
        return passages
    best_position = max(scores, key=lambda position: (scores[position], -position))
    best = chunks[best_position]
    if any(hit.get("chunk_id") == best.get("chunk_id") for hit in passages):
        return passages
    if not _plausible(best, rank_map, total):
        return passages
    injected = {
        "score": None,
        "chunk_id": best["chunk_id"],
        "chapter": best["chapter"],
        "heading": best.get("heading", ""),
        "text": best.get("text", ""),
        "source": best.get("source", ""),
    }
    return passages[:-1] + [injected]
