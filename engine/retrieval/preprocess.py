import functools
import re
import unicodedata
from pathlib import Path

from vendor.snowballstemmer import stemmer as _make_stemmer

TOKEN = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")

TYPOGRAPHIC = str.maketrans(
    {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
)

STOPWORDS = frozenset(
    line.strip()
    for line in (Path(__file__).resolve().parents[2] / "vendor" / "stopwords-en.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip() and not line.startswith("#")
)

_ENGLISH = _make_stemmer("english")


def token_spans(text):
    for match in TOKEN.finditer(text or ""):
        yield match.start(), match.end(), match.group()


def tokens(text):
    return [token for _, _, token in token_spans(text)]


def words(text):
    return [token.lower() for token in tokens(text)]


@functools.lru_cache(maxsize=2048)
def fold(text):
    folded = unicodedata.normalize("NFKC", text or "")
    return folded.translate(TYPOGRAPHIC).casefold()


@functools.lru_cache(maxsize=8192)
def stem(word):
    return _ENGLISH.stemWord(fold(word))


def stemmed_words(text):
    return [stem(word) for word in words(fold(text))]


@functools.lru_cache(maxsize=1024)
def normalize(text):
    folded = unicodedata.normalize("NFKC", text or "")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in folded.split("\n")]
    return "\n".join(lines).strip()
