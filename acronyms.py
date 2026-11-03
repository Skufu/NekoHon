"""The book's own spelling of a short acronym, used as the asked question.

Measured reason (2026-11-01): "what is ai" against AI Engineering. Two
stopwords and a two-letter token leave the embedder nothing to rank on — the
top five sat inside 0.006 (0.8% relative), an ordering of noise, and the one
chunk that defines the term (ch06-047, the Russell and Norvig sentence) landed
fifth, 0.006 behind. The definition reorder in answer.py cannot rescue it: it
keeps words longer than two characters, so it sees no head term at all. The
book spells the words out, and asking with them is the same question:
"what is artificial intelligence" leads with the defining chunk.

The spelling is read from the book, never from a table here: a capitalised run
whose initials match the acronym ("Artificial Intelligence"), or a
parenthetical definition that closes with it ("Customer relationship
management (CRM)"). The most repeated spelling wins; a run containing a
stopword ("And I") is not evidence.
"""

import re

from preprocess import STOPWORDS

_MIN_WORDS = 2
_MAX_WORDS = 4
_MIN_HEAD = 2
_MAX_HEAD = 3

# "Customer relationship management (CRM)" — the acronym follows its words.
_PARENTHETICAL_RE = re.compile(
    r"([A-Za-z][\w'’-]*(?:\s+[A-Za-z][\w'’-]*){1,3})\s*\(([A-Z]{2,4})s?\)"
)
# "Artificial Intelligence: A Modern Approach" — the words carry the initials.
_CAPITAL_RUN_RE = re.compile(r"[A-Z][A-Za-z'’-]*(?:\s+[A-Z][A-Za-z'’-]*){1,3}")
# "what is ai", "what's an api?", "define crm" — a single short head term. The
# reader may name the source after it ("what is ai based on this book"); that
# clause says which book to use, it is not a concept to retrieve, and the words
# "book" or "chapter" only pull preface chunks into the window.
_FRAMING_TAIL = (
    r"(?:\s+(?:based\s+on|according\s+to|in|from|per)\s+"
    r"(?:this|the)\s+(?:book|text|chapter|section|passage|author|authors?))?"
)
_ASK_RE = re.compile(
    r"^(?P<prefix>\s*(?:what\s+(?:is|are)|what's|define)\s+(?:an?|the)?\s*)"
    r"(?P<head>[A-Za-z][A-Za-z0-9]{1,2})"
    + _FRAMING_TAIL
    + r"(?P<suffix>\s*[?.!]*\s*)$",
    re.I,
)

_CACHE = {}
_CACHE_MAX = 4


def _vote(votes, acronym, words):
    if not all(len(word) >= 2 and word.lower() not in STOPWORDS for word in words):
        return
    phrase = " ".join(word.lower() for word in words)
    tally = votes.setdefault(acronym, {})
    tally[phrase] = tally.get(phrase, 0) + 1


def _collect(text, votes):
    for match in _PARENTHETICAL_RE.finditer(text):
        run, acronym = match.group(1).split(), match.group(2).lower()
        for width in range(_MIN_WORDS, min(_MAX_WORDS, len(run)) + 1):
            phrase = run[-width:]
            if "".join(word[0] for word in phrase).lower() == acronym:
                _vote(votes, acronym, phrase)
    for match in _CAPITAL_RUN_RE.finditer(text):
        run = match.group(0).split()
        for width in range(_MIN_WORDS, min(_MAX_WORDS, len(run)) + 1):
            phrase = run[:width]
            _vote(votes, "".join(word[0] for word in phrase).lower(), phrase)


def spellings(index):
    """acronym (lowercase) -> the words the book spells it with, or {}."""
    key = (id(index), len(index.get("chunks") or []))
    cached = _CACHE.get(key)
    # The cached entry holds the index it was built from: a collected dict can
    # hand its id to the next index, and a stale spelling would then answer for
    # the wrong book.
    if cached is not None and cached[0] is index:
        return cached[1]
    votes = {}
    for chunk in index.get("chunks") or []:
        text = chunk.get("text") or ""
        if text:
            _collect(text, votes)
    best = {}
    for acronym, tally in votes.items():
        if not _MIN_HEAD <= len(acronym) <= _MAX_HEAD:
            continue
        # Most repeated spelling; a tie goes to the longer phrase, which is the
        # more specific one ("artificial intelligence" over "artificial").
        phrase, _ = max(tally.items(), key=lambda item: (item[1], len(item[0])))
        best[acronym] = phrase
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = (index, best)
    return best


def expand(index, question):
    """The question with its acronym head spelled out, or None.

    Only a single short head term is rewritten ("what is ai" -> "what is
    artificial intelligence"); a longer ask carries enough words for dense
    search to rank on and is left alone.
    """
    match = _ASK_RE.match(question or "")
    if not match:
        return None
    head = match.group("head").lower()
    phrase = spellings(index).get(head)
    if not phrase or phrase == head:
        return None
    return match.group("prefix") + phrase + match.group("suffix")
