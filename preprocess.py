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
and the quote check compares against it. Every function here is a view over it
and none writes back.

The pipeline stages, kept separate on purpose:

- 5 text processing: `normalize()` for the dense view, `fold()` for matching.
  Both start with NFKC; `fold()` additionally repairs typographic punctuation
  (NFKC does not touch curly quotes or dashes) and casefolds.
- 6 punctuation: `tokens()` speak words only; punctuation never becomes a
  token here, and no stage rewrites `chunk["text"]`.
- 7 tokenization: `tokens()`/`words()` are the only tokenizer, used by
  `postings`, `anchor_words`, `rare`, `boost`, and the readings.
- 8 stop words: `STOPWORDS`, the SMART list, vendored as data in
  `vendor/stopwords-en.txt` with its source in the file header. A filter for
  matching views; never a rewrite.
- 9 stemming: `stem()` and `stemmed_words()`, the standard Snowball English
  (Porter2) stemmer, vendored in `vendor/snowballstemmer/` (BSD-3-Clause; see
  its COPYING). Idempotent on the measured word set.

Stages 5-9 are new views. Wiring them into the keyword/anchor path changes
which words match, so it is proposed in `artifacts/reports/stage9-preprocessing.md`
and waits for a battery run; `words()` and `normalize()` keep their exact
behavior until then, because the rare gate rides on the raw df counts.
"""

import functools
import re
import unicodedata
from pathlib import Path

from vendor.snowballstemmer import stemmer as _make_stemmer

TOKEN = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")

# NFKC maps ﬁ→fi, ①→1, full-width Ａ→A, and no-break space→space, but it does
# not touch typographic quotes or dashes; those are folded by hand so that a
# curly apostrophe matches a straight one in the matching view.
TYPOGRAPHIC = str.maketrans(
    {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
)

STOPWORDS = frozenset(
    line.strip()
    for line in (Path(__file__).resolve().parent / "vendor" / "stopwords-en.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip() and not line.startswith("#")
)

_ENGLISH = _make_stemmer("english")


def token_spans(text):
    """(start, end, token) for each token, for callers that must rewrite in place."""
    for match in TOKEN.finditer(text or ""):
        yield match.start(), match.end(), match.group()


def tokens(text):
    """The word tokens of a text, in the spelling the source used.

    Pure digits are not tokens: "1/17" reads as nothing. Alphanumeric terms
    containing at least one ASCII letter ("S3", "3NF", "DDR4") are preserved
    intact as single tokens.
    """
    return [token for _, _, token in token_spans(text)]


def words(text):
    """The folded tokens of a text. Same function on both sides of the index."""
    return [token.lower() for token in tokens(text)]


@functools.lru_cache(maxsize=2048)
def fold(text):
    """The matching fold: NFKC, typographic punctuation to ASCII, casefolded.

    The view for equality-style matching (stopword checks, stem inputs, future
    keyword maps). `normalize()` is the dense view and keeps case and
    typography; `chunk["text"]` stays canonical either way.
    """
    folded = unicodedata.normalize("NFKC", text or "")
    return folded.translate(TYPOGRAPHIC).casefold()


@functools.lru_cache(maxsize=8192)
def stem(word):
    """The Snowball English (Porter2) stem of one word.

    The standard implementation, vendored under `vendor/snowballstemmer/`
    (BSD-3-Clause), so the runtime needs no pip and no network. The whole
    "extract" family lands on one form: stem("extracted") ==
    stem("extract") == stem("extracting"). Idempotent: stem(stem(w)) ==
    stem(w) on the measured word set.
    """
    return _ENGLISH.stemWord(fold(word))


def stemmed_words(text):
    """The stemmed lexical view: `fold()`, then `words()`, then `stem()`.

    Folding before tokenizing is what lets NFKC reach the tokenizer: a ligature
    like ﬁ only becomes "fi" if the text is folded first, otherwise the
    regex sees the ligature as punctuation and strands the "le". A view over
    chunk text, never a rewrite: the citation and the quote check still read
    `chunk["text"]`.
    """
    return [stem(word) for word in words(fold(text))]


@functools.lru_cache(maxsize=1024)
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
