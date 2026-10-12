"""A self-proving second reading when a question word is not in the book.

`spelling.py` repaired the question in two places: one path rewrote the string
the model saw, another re-searched and kept the result when the top score
improved. The reader was answered a question they never asked, and the repair
lived outside the retriever that could judge it.

What is left is one reading. A word absent from the book is swapped for the one
book word it is closest to, the question is read again with that word, and the
reading is kept only when its best dense score strictly beats the literal one.
The reading becomes the question the model answers, and the answer says so in
one line (`Read as: ...`). Nothing is repaired silently.

Measured 2026-10-12 on why the disclosure is a line and not a hint: six shapes
of hint (a plain note, a quoted note, a system-level rule, and a bracket on the
question line) all returned exactly `Not in this book.` for "What does CRU
stand for?" while five passages were attached, because the model will not map
`CRU [book: "CRUD"]` onto the passage's `CRUD`. The reading as the question
does answer. Retrieval alone never needed the swap for CRU (ch05-019 is dense
rank 1); the *answer* did.

Measured 2026-10-12 (nomic, data/index.json):
- "what is a atermark?" 0.573 ch03-006 -> "what is a watermark?" 0.817 ch08-040,
  kept (+0.244),
- "What is the capital of France?" 0.544 -> "... of Franca?" 0.530, dropped
  (-0.014) even though the swap is one letter away,
- "What does CRU stand for?" 0.675 ch05-019 -> "... CRUD ...?" 0.785, same chunk.
  Retrieval never needed the swap; the answer did. Untouched, the model reads
  "CRU", does not find it in the passage, and refuses.

The improvement gate is the safety, not the similarity cutoff: the France
reading loses, so it cannot inject a passage about franca.

Stdlib only. The embedder is injected so tests never call Ollama.
"""

import difflib

from keywords import WORD, postings
from retrieve import DEFAULT_EMBEDDER, rank_chunks

CUTOFF = 0.85


def _closest(word, vocabulary):
    """(score, word, runner_up) for the closest book word."""
    best_score = 0.0
    best_word = ""
    runner_up = 0.0
    for candidate in vocabulary:
        score = difflib.SequenceMatcher(None, word, candidate).ratio()
        if score > best_score:
            best_score, best_word, runner_up = score, candidate, best_score
        elif score > runner_up:
            runner_up = score
    return best_score, best_word, runner_up


def _fixes(question, word_map):
    """[(start, end, word as typed, book word)] for words worth re-reading.

    A swap needs one candidate over CUTOFF and no tie at the top.
    """
    text = question or ""
    vocabulary = sorted(word_map)
    if not vocabulary:
        return []
    fixes = []
    seen = set()
    for match in WORD.finditer(text):
        word = match.group().lower()
        if word in word_map or word in seen:
            continue
        seen.add(word)
        score, candidate, runner_up = _closest(word, vocabulary)
        if score < CUTOFF or score <= runner_up:
            continue
        fixes.append((match.start(), match.end(), match.group(), candidate))
    return fixes


def _applied(text, fixes):
    parts = []
    cursor = 0
    for start, end, _, book_word in fixes:
        parts.append(text[cursor:start])
        parts.append(book_word)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def resolved_reading(question, word_map):
    """The question with out-of-book words swapped for their closest book word.

    The question comes back unchanged when nothing resolves, so callers can
    compare strings.
    """
    text = question or ""
    return _applied(text, _fixes(text, word_map))


def _book_forms(index):
    """folded word -> the spelling the book uses, first occurrence.

    postings() folds case, and an acronym must go back to the question in the
    book's own shape: "CRUD", not "crud".
    """
    forms = {}
    for chunk in index.get("chunks") or []:
        for match in WORD.finditer(chunk.get("text") or ""):
            forms.setdefault(match.group().lower(), match.group())
    return forms


def second_reading(index, question, literal_top, model=DEFAULT_EMBEDDER,
                   embed_fn=None, word_map=None):
    """{"reading": question, "chunk": passage, "swaps": {typed: book}} or None.

    literal_top is the best score the literal question already produced, so the
    literal ranking is never computed twice.
    """
    word_map = postings(index) if word_map is None else word_map
    if not word_map:
        return None
    fixes = _fixes(question, word_map)
    if not fixes:
        return None
    reading = _applied(question or "", fixes)
    ranked = rank_chunks(index, reading, model, embed_fn)
    if not ranked or ranked[0][0] <= literal_top:
        return None
    score, chunk = ranked[0]
    forms = _book_forms(index)
    return {
        "reading": reading,
        "chunk": {
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "chapter": chunk["chapter"],
            "heading": chunk.get("heading", ""),
            "text": chunk.get("text", ""),
            "source": chunk.get("source", ""),
        },
        "swaps": {
            typed.lower(): forms.get(book, book)
            for _, _, typed, book in fixes
        },
    }
