from engine.retrieval.preprocess import STOPWORDS, tokens, words

from types import MappingProxyType

RARE_DF = 8
COVER_DF = 80


def book_forms(index):
    if isinstance(index, dict) and "_book_forms" in index:
        return index["_book_forms"]
    forms = {}
    chunks = index.get("chunks") if isinstance(index, dict) else index
    for chunk in chunks or []:
        text = chunk.get("text") if isinstance(chunk, dict) else str(chunk)
        for token in tokens(text):
            forms.setdefault(token.lower(), token)
    if isinstance(index, dict):
        index["_book_forms"] = forms
    return forms


class _PostingPositions(tuple):
    def __eq__(self, other):
        if isinstance(other, list):
            return list(self) == other
        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)


_POSTINGS_CACHE = {}


def postings(index):
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
    res = set()
    for word in words(question):
        if word not in STOPWORDS:
            pos = word_map.get(word)
            if pos and len(pos) <= bound:
                res.add(word)
    return res


def rare(question, word_map, bound=None):
    if bound is None:
        bound = RARE_DF
    for word in set(words(question)):
        pos = word_map.get(word)
        if pos and len(pos) <= bound:
            return True
    return False
