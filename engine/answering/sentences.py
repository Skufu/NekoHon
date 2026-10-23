import functools
import re

from engine.retrieval.preprocess import tokens as _pre_tokens, words as _pre_words


@functools.lru_cache(maxsize=4096)
def _cached_words(text):
    return tuple(_pre_words(text))


def cached_words(text):
    return list(_cached_words(text))


@functools.lru_cache(maxsize=4096)
def _cached_tokens(text):
    return tuple(_pre_tokens(text))


def cached_tokens(text):
    return list(_cached_tokens(text))


WHITESPACE_RE = re.compile(r"\s+")


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


_TERMINAL_PUNCT_RE = re.compile(r'[.!?]["\'”’]?$')


_CHAPTER_PREFIX_RE = re.compile(r"^Chapter\s+\d+\b", re.I)


@functools.lru_cache(maxsize=1024)
def token_word_pattern(token):
    return re.compile(rf"\b{re.escape(token)}\b")


@functools.lru_cache(maxsize=1024)
def heading_prefix_pattern(heading):
    words_list = heading.split()
    if not words_list:
        return None
    pat_str = r"\s*".join(re.escape(w) for w in words_list)
    return re.compile(rf"\s*{pat_str}[\s:\u2014-]*", re.I)


@functools.lru_cache(maxsize=512)
def words_pattern(quote):
    words_list = (quote or "").split()
    if not words_list:
        return None
    return re.compile(r"\s+".join(re.escape(w) for w in words_list), re.I)


KEY_MIN_CHARS = 40


@functools.lru_cache(maxsize=2048)
def collapse_lower(text):
    return WHITESPACE_RE.sub(" ", text or "").lower()


@functools.lru_cache(maxsize=1024)
def _candidate_sentences_cached(text, heading=""):
    raw = (text or "").strip()
    if not raw:
        return ()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    raw_candidates = []
    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines() if line.strip()]
        if not lines:
            continue
        body_lines = []
        for i, line in enumerate(lines):
            if i == 0 and len(lines) > 1 and not line.endswith((".", "?", "!", ":", ";", '"', "'", "”")):
                raw_candidates.append(line)
            else:
                body_lines.append(line)
        if body_lines:
            body_text = " ".join(body_lines)
            parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(body_text) if s.strip()]
            raw_candidates.extend(parts)

    if not raw_candidates:
        return ()

    head_norm = (heading or "").strip().lower()
    has_terminal = any(_TERMINAL_PUNCT_RE.search(s.strip()) for s in raw_candidates)

    filtered = []
    for s in raw_candidates:
        s_strip = s.strip()
        if not s_strip:
            continue
        if head_norm and s_strip.lower() == head_norm:
            continue
        if _CHAPTER_PREFIX_RE.match(s_strip) and not _TERMINAL_PUNCT_RE.search(s_strip):
            continue
        if has_terminal and not _TERMINAL_PUNCT_RE.search(s_strip):
            continue
        filtered.append(s_strip)

    return tuple(filtered if filtered else raw_candidates)


def candidate_sentences(text, heading=""):
    return list(_candidate_sentences_cached(text, heading))


FOOTNOTE_GLUE = re.compile(r"\b[A-Z][a-z]{2,}(\d{1,3})(?=\s+[A-Z][a-z])")


@functools.lru_cache(maxsize=1024)
def _sentences_cached(text):
    raw = (text or "").strip()
    lines = raw.splitlines()
    if len(lines) > 1 and not lines[0].strip().endswith((".", "?", "!")):
        raw = "\n".join(lines[1:])
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(raw) if p.strip()]
    parts = []
    for para in paragraphs:
        flat = WHITESPACE_RE.sub(" ", para).strip()
        for run in SENTENCE_SPLIT_RE.split(flat):
            cursor = 0
            for match in FOOTNOTE_GLUE.finditer(run):
                parts.append(run[cursor:match.end()])
                cursor = match.end()
            parts.append(run[cursor:])
    sentences = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) < KEY_MIN_CHARS:
            continue
        if sentence[0].isupper() and sentence.endswith((".", "?", "!")):
            sentences.append(sentence)
    return tuple(sentences)


def split_sentences(text):
    return list(_sentences_cached(text))
