"""The one text seam. The index side and the query side come through here.

Two channels, two needs (the README's keyword/vector split):

- the dense channel keeps grammar, punctuation, case, and negation, because the
  embedder was trained on prose. `normalize()` is that view: NFKC, then runs of
  horizontal whitespace folded to one space, newlines kept because a chunk's
  first line is its heading. It is applied at embed time only, in
  `retrieve.format_input`, on both the document and the query side — the two
  must travel together, so changing it means rebuilding the index, not just
  editing this function. On this book it moves 3 chunks of 1065, so it buys
  almost nothing here; it is wired for the next book, whose EPUB may carry
  ligatures, non-breaking spaces, or full-width characters.
- the lexical channel wants tokens. `tokens()` and `words()` are the only
  tokenizers, used by `postings`, `anchor_words`, `rare`, `boost`, and the
  readings, so the two sides of the index cannot drift apart. Symmetry by
  construction, not by discipline: before this, five call sites each ran their
  own `.lower()` over the same regex.

`chunk["text"]` is canonical and is never rewritten — it is what gets cited,
and the quote check compares against it. Both functions here are views over it,
and neither writes back.
"""

import re
import unicodedata

TOKEN = re.compile(r"[A-Za-z]+")


def token_spans(text):
    """(start, end, token) for each token, for callers that must rewrite in place."""
    for match in TOKEN.finditer(text or ""):
        yield match.start(), match.end(), match.group()


def tokens(text):
    """The word tokens of a text, in the spelling the source used.

    Digits are not tokens: "S3" reads as "s" and "1/17" reads as nothing. That
    is today's behavior and it is kept on purpose, because widening it moves
    every df count in the book and the rare gate rides on those counts. Widen
    it only with the pins in front of you.
    """
    return [token for _, _, token in token_spans(text)]


def words(text):
    """The folded tokens of a text. Same function on both sides of the index."""
    return [token.lower() for token in tokens(text)]


def normalize(text):
    """The dense-channel view: NFKC, then runs of spaces folded to one.

    Newlines stay, because a chunk's first line is its heading and the dense
    text keeps that shape. Applied at embed time only: `chunk["text"]` stays
    canonical and is what gets cited, so this never edits the book.

    The document side and the query side must use this same function. Turning
    it on without rebuilding the index leaves the query view and the stored
    vectors in different spaces, which degrades silently.
    """
    folded = unicodedata.normalize("NFKC", text or "")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in folded.split("\n")]
    return "\n".join(lines).strip()
