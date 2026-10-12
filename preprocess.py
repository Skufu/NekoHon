"""The one text seam. The index side and the query side come through here.

Two channels, two needs (the README's keyword/vector split):

- the dense channel keeps grammar, punctuation, case, and negation, because the
  embedder was trained on prose. `normalize()` is that view, and it is
  deliberately the identity today. It changes the bytes every vector in
  `data/index.json` was built from, so it moves only with a new index file and
  a rerun of the golden set, the typos, the probes, and France.
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
    """The dense-channel view. The identity until a bake-off says otherwise.

    The candidates are NFKC and whitespace folding. Both rewrite the bytes an
    embedder sees, so neither ships without `data/index.<name>.json` and a
    rerun of the pins; swapping a live index under the same name is exactly the
    move the hard rules forbid.
    """
    return text or ""
