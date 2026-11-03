"""Rare-word gate and paragraph anchors. Post-v1 retrieval work.

Gate: a question word living in at most RARE_DF chunks marks the question as
carrying rare vocabulary, and a word the book itself capitalises marks the
question as naming something the book names (a person, a product, an acronym).
Either one justifies the lexical channel joining, via `lexical_terms`; the
band that decides whether lexical evidence may reorder a passage lives in
fusion.py. The `rare` semantics are unchanged and still exported, because the
readings and the tests call it directly.

Capitalisation is the cheap, model-free signal for "named": a proper name is
written capitalised in nearly every mention, a common word only when it opens
a sentence. Measured on `data/index.ddia.sqlite` (2026-11-02): `cdc` is
capitalised in 9 of 9 mentions, `mapreduce` 86 of 86, while `data` is
capitalised in 16% and `if` in 38%. The scan costs 59 ms cold on that index
and nothing warm, because the answer is cached on the index object.

Anchors: question words rare enough in the book (df <= COVER_DF) that
finding one in a paragraph makes it answering material. A fixed English
word list for list questions is not shippable (sampled list words range
from df=1 to df=77, no natural cutoff); the book's own counts are. Function
words are never anchors: the SMART stopword list (see preprocess.STOPWORDS)
filters them first, so a rare-in-book function word like "actually" cannot
trigger a paragraph expansion (stage 8 of preprocessing, wired 2026-10-13).
Stdlib only; no model, no download.
"""

from preprocess import STOPWORDS, tokens, words

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
    first_text = chunks[0].get("text") if chunks and isinstance(chunks[0], dict) else (chunks[0] if chunks else None)
    key = (id(chunks), len(chunks), chunks[0].get("chunk_id") if chunks and isinstance(chunks[0], dict) else None, hash(str(first_text)))
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


# A word counts as named by the book when the book writes it capitalised in at
# least NAMED_DF chunks and capitalises at least NAMED_SHARE of its mentions.
# Two is the floor for a name rather than a typographic accident: one capitalised
# mention is a heading or a sentence opening. The share decides named versus
# merely sentence-initial, and is measured, not fitted to a test: on ddia
# (2026-11-02) `mapreduce` is capitalised in 86 of 86 mentions and `cdc` in 9 of
# 9, while `data` is capitalised in 16% and `if` in 38%; on the novel the five
# entity names are 100%. Half sits in the gap with margin on both sides.
NAMED_DF = 2
NAMED_SHARE = 0.5

_NAMED_CACHE = {}


def _chunk_key(chunks):
    """Identity of a chunk list, so a cached answer cannot outlive an index."""
    first = chunks[0] if chunks else None
    if isinstance(first, dict):
        chunk_id = first.get("chunk_id")
        text = first.get("text")
    else:
        chunk_id = None
        text = first
    return (id(chunks), len(chunks), chunk_id, hash(str(text)))


def named_words(index):
    """The words the book itself capitalises: names, acronyms, labels.

    The scan reads each chunk's tokens in their source spelling once and counts,
    per folded word, how many chunks capitalise it and how many of its mentions
    are capitalised. The result is a frozenset cached on the index dict under
    `_named_words` with the chunk list's identity, so a replaced chunk list
    recomputes instead of serving the old vocabulary. Measured 2026-11-02 on
    `data/index.ddia.sqlite` (1306 chunks): 59 ms cold, no cost warm. A bare
    chunk list (not an index dict) uses the module cache, capped like postings.

    Stopwords are excluded: a capitalised function word is sentence position,
    not a name, and "I" is capitalised in every mention of a first-person book.
    """
    if isinstance(index, dict):
        chunks = index.get("chunks") or []
    else:
        chunks = index or []
    key = _chunk_key(chunks)
    if isinstance(index, dict):
        cached = index.get("_named_words")
        if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == key:
            return cached[1]
    else:
        cached = _NAMED_CACHE.get(key)
        if cached is not None:
            return cached

    chunks_capitalised = {}
    capitalised = {}
    total = {}
    for chunk in chunks:
        text = chunk.get("text") if isinstance(chunk, dict) else str(chunk)
        seen = set()
        for token in tokens(text or ""):
            word = token.lower()
            total[word] = total.get(word, 0) + 1
            if word in STOPWORDS or not token[:1].isupper():
                continue
            capitalised[word] = capitalised.get(word, 0) + 1
            seen.add(word)
        for word in seen:
            chunks_capitalised[word] = chunks_capitalised.get(word, 0) + 1

    named = frozenset(
        word
        for word, count in chunks_capitalised.items()
        if count >= NAMED_DF and capitalised[word] / total[word] >= NAMED_SHARE
    )

    if isinstance(index, dict):
        index["_named_words"] = (key, named)
    else:
        if len(_NAMED_CACHE) >= 16:
            try:
                _NAMED_CACHE.pop(next(iter(_NAMED_CACHE)))
            except Exception:
                _NAMED_CACHE.clear()
        _NAMED_CACHE[key] = named
    return named


def lexical_terms(index, question, word_map):
    """The question terms that justify a lexical (BM25) pass.

    A term qualifies when it is rare in the book, the old trigger, or when the
    book names it: capitalised in at least NAMED_DF chunks. The old gate asked
    "is this word barely used?", which is the wrong question for a name: on the
    novel `atofe` lives in 51 chunks, `rudeus` in 65 and `sandor` in 115, so the
    lexical leg never joined a "who is X" ask and the answer came from one
    scene. The names are the book's most repeated vocabulary, not its rarest.

    Returns folded question words in the order asked, duplicates dropped. The
    named set is computed lazily: a question whose every word is rare or absent
    never pays for the scan.
    """
    named = None
    res = []
    seen = set()
    for word in words(question):
        if word in seen:
            continue
        seen.add(word)
        pos = word_map.get(word)
        if pos and len(pos) <= RARE_DF:
            res.append(word)
            continue
        if pos:
            if named is None:
                named = named_words(index)
            if word in named:
                res.append(word)
    return res
