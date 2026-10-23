import difflib
import urllib.error

from engine import llm
from engine.retrieval.keywords import book_forms, postings
from engine.retrieval.preprocess import stem, token_spans, tokens
from engine.retrieval.retrieve import DEFAULT_EMBEDDER, rank_chunks

CUTOFF = 0.85

SPELL_SYSTEM = """Fix any spelling errors in the user-provided book search query below.
Correct only clear, high-confidence typos. Do not rewrite, add, remove, or reorder words.
Preserve punctuation and capitalization unless a change is required for a typo fix.
If there are no spelling errors, or if you're unsure, output the original query unchanged.
Output only the final query text, nothing else."""


def _closest(word, vocabulary):
    best_score = 0.0
    best_word = ""
    runner_up = 0.0
    s = difflib.SequenceMatcher(None, word)
    l1 = len(word)
    for candidate in vocabulary:
        l2 = len(candidate)
        upper = 2 * min(l1, l2) / (l1 + l2)
        if upper <= runner_up:
            continue
        s.set_seq2(candidate)
        if s.real_quick_ratio() <= runner_up:
            continue
        if s.quick_ratio() <= runner_up:
            continue
        score = s.ratio()
        if score > best_score:
            best_score, best_word, runner_up = score, candidate, best_score
        elif score > runner_up:
            runner_up = score
    return best_score, best_word, runner_up


_SORTED_WMAP_CACHE = {}


def clear_wmap_cache():
    _SORTED_WMAP_CACHE.clear()


def _fixes(question, word_map):
    text = question or ""
    wmap_key = id(word_map)
    entry = _SORTED_WMAP_CACHE.get(wmap_key)
    if entry is not None and entry[0] == len(word_map):
        vocabulary = entry[1]
    else:
        vocabulary = sorted(word_map)
        if len(_SORTED_WMAP_CACHE) >= 16:
            try:
                _SORTED_WMAP_CACHE.pop(next(iter(_SORTED_WMAP_CACHE)))
            except Exception:
                _SORTED_WMAP_CACHE.clear()
        _SORTED_WMAP_CACHE[wmap_key] = (len(word_map), vocabulary)

    if not vocabulary:
        return []
    fixes = []
    seen = set()
    for start, end, token in token_spans(text):
        word = token.lower()
        if word in word_map or word in seen:
            continue
        is_mid_title = start > 0 and token[0].isupper() and token[1:].islower()
        is_mixed_case = any(c.isupper() for c in token) and any(c.islower() for c in token) and any(c.isupper() for c in token[1:])
        has_digit = any(c.isdigit() for c in token)
        if is_mid_title or is_mixed_case or has_digit:
            continue
        seen.add(word)
        score, candidate, runner_up = _closest(word, vocabulary)
        if score < CUTOFF or score <= runner_up:
            continue
        if stem(word) == stem(candidate):
            continue
        fixes.append((start, end, token, candidate))
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
    text = question or ""
    return _applied(text, _fixes(text, word_map))


def _clean_completion(text):
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return " ".join(text.split())


def llm_second_reading(index, question, literal_top, answer_model=llm.ANSWER_MODEL,
                       generate_fn=None, embed_model=DEFAULT_EMBEDDER,
                       embed_fn=None, word_map=None):
    if generate_fn is None:
        generate_fn = llm.generate
    word_map = postings(index) if word_map is None else word_map
    before = [token.lower() for token in tokens(question or "")]
    if not word_map or not any(word not in word_map for word in before):
        return None
    try:
        completion = generate_fn(
            SPELL_SYSTEM, f'User query: "{question}"', answer_model
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError):
        return None
    corrected = _clean_completion(completion)
    after = [token.lower() for token in tokens(corrected)]
    if not corrected or set(after) == set(before) or len(after) != len(before):
        return None
    ranked = rank_chunks(index, corrected, embed_model, embed_fn)
    if not ranked or ranked[0][0] <= literal_top:
        return None
    score, chunk = ranked[0]
    return {
        "reading": corrected,
        "chunk": {
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "chapter": chunk["chapter"],
            "heading": chunk.get("heading", ""),
            "text": chunk.get("text", ""),
            "source": chunk.get("source", ""),
        },
        "swaps": {
            typed: fixed
            for typed, fixed in zip(before, after)
            if typed != fixed
        },
    }


def second_reading(index, question, literal_top, model=DEFAULT_EMBEDDER,
                   embed_fn=None, word_map=None):
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
    forms = book_forms(index)
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
