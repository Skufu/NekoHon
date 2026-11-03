"""Which generation settings a book gets, decided by what kind of book it is.

A technical book is answered from a definition that has to come out the same
way twice, so it is asked cold (temperature 0), from five passages, in one
quote plus one gloss line. A novel is not a definition: the reader wants the
scene, several moments that bear on the question, and prose that does not
read like a lookup. That book gets a warmer sampler, more passages, and the
model's own paragraph kept instead of trimmed to a single line.

The kind is `index["kind"]` when the index carries one (ingest writes it
with `--kind`). Otherwise it is read off the text. Measured 2026-11-01 over
every index in `data/`, dialogue ratio and the share of chunks that carry
any dialogue:

|book|dialogue ratio|chunks with dialogue|
|---|---|---|
|Quantization|0.0182|0.277|
|Fundamentals of Data Engineering|0.0186|0.203|
|AI Engineering|0.0189|0.269|
|Data-Intensive Applications|0.0477|0.469|
|AI Agents|0.0756|0.436|
|Mushoku Tensei (novel)|0.1651|0.869|

Dialogue separates them with room to spare: the loudest technical book is
0.076 and the novel is 0.165, so the line sits at 0.12, with a second gate on
the share of chunks that carry any dialogue at all (0.70; the highest
technical book is 0.47). A non-fiction book that quotes interviews heavily
lands between those and is misread as fiction — the remedy is to store
`kind` in the index, which always wins over the guess.
"""

import os
import re

from prompt import (
    FICTION_ANSWER_WORDS,
    FICTION_GENERATION_OPTIONS,
    GENERATION_OPTIONS,
    SYSTEM,
    SYSTEM_ANSWER,
    SYSTEM_ANSWER_FICTION,
    SYSTEM_FICTION,
    TECHNICAL_ANSWER_WORDS,
    answer_gloss_system,
    compare_system,
    fiction_system,
    followup_gloss_system,
    technical_system,
)

NONFICTION = "nonfiction"
FICTION = "fiction"
KINDS = (NONFICTION, FICTION)

# A quoted stretch long enough to be speech, not an apostrophe or a scare quote.
_QUOTED = re.compile(r"[“\"]([^”\"]{2,400})[”\"]")

FICTION_DIALOGUE_RATIO = 0.12
FICTION_DIALOGUE_CHUNK_SHARE = 0.70

NONFICTION_PASSAGE_LIMIT = 5
# The four fiction knobs are environment-readable so a new book can be tried
# without an edit: FICTION_PASSAGE_LIMIT, FICTION_QUOTE_TARGET,
# FICTION_SAMPLE_ROUNDS, FICTION_TEMPERATURE (prompt.py).
FICTION_PASSAGE_LIMIT = int(os.environ.get("FICTION_PASSAGE_LIMIT", "8"))

# A 2B model reads "quote two or three passages" and still writes one, so the
# count is reached by asking again: each round is one generation, and the
# rounds stop as soon as the answer holds this many distinct passages.
# Measured 2026-11-01 on the novel: one prompt shape produced 8 single-quote
# answers in 8 questions; two rounds produced two passages in 6 of 8.
# Measured 2026-11-01 on the novel, eight questions: one round cited one
# passage in every answer; three rounds (later rounds dropping the passages
# already quoted) cited two in six of the eight, mean 1.75 citations, and the
# answer grew from 246 to 336 characters. Two rounds answer in 7-8 s on an
# idle machine; three under load reached 31 s.
FICTION_QUOTE_TARGET = int(os.environ.get("FICTION_QUOTE_TARGET", "2"))
FICTION_QUOTE_MAX = 3
FICTION_SAMPLE_ROUNDS = int(os.environ.get("FICTION_SAMPLE_ROUNDS", "3"))


def features(index):
    """Dialogue statistics for a loaded index. Empty index gives zeros."""
    chunks = index.get("chunks") or []
    text = "\n".join(str(chunk.get("text") or "") for chunk in chunks)
    total = len(text)
    quoted = sum(len(match) for match in _QUOTED.findall(text))
    with_dialogue = sum(1 for chunk in chunks if _QUOTED.search(str(chunk.get("text") or "")))
    return {
        "chunks": len(chunks),
        "chars": total,
        "dialogue_ratio": (quoted / total) if total else 0.0,
        "dialogue_chunk_share": (with_dialogue / len(chunks)) if chunks else 0.0,
    }


def detect_kind(index):
    """`fiction` when the text is mostly people talking, else `nonfiction`."""
    measured = features(index)
    if (
        measured["dialogue_ratio"] >= FICTION_DIALOGUE_RATIO
        and measured["dialogue_chunk_share"] >= FICTION_DIALOGUE_CHUNK_SHARE
    ):
        return FICTION
    return NONFICTION


def kind(index):
    """The stored kind when the index carries one, else the detected kind."""
    stored = str(index.get("kind") or "").strip().lower()
    if stored in KINDS:
        return stored
    return detect_kind(index)


def _token_cap(words, options):
    """The generation cap a word target needs, never below the measured one."""
    if not words:
        return dict(options)
    sized = dict(options)
    sized["num_predict"] = max(int(options["num_predict"]), int(words) * 2)
    return sized


def answer_words(index):
    """The word target for this book's own prose, 0 when the default stands."""
    return FICTION_ANSWER_WORDS if kind(index) == FICTION else TECHNICAL_ANSWER_WORDS


def for_index(index):
    """Everything the answer path varies by kind: system, passage count, sampler.

    `keep_body` means the model's multi-sentence paragraph is the answer, so
    the one-line gloss rewrite is skipped; the citation gate still applies.
    """
    kind_of_book = kind(index)
    if kind_of_book == FICTION:
        return {
            "kind": FICTION,
            "system": fiction_system(FICTION_ANSWER_WORDS),
            "system_plain": SYSTEM_ANSWER_FICTION,
            "gloss_system": answer_gloss_system(FICTION_ANSWER_WORDS),
            "compare_system": compare_system(FICTION_ANSWER_WORDS),
            "followup_system": followup_gloss_system(FICTION_ANSWER_WORDS),
            "passage_limit": FICTION_PASSAGE_LIMIT,
            "options": _token_cap(FICTION_ANSWER_WORDS, FICTION_GENERATION_OPTIONS),
            "keep_body": True,
            "answer_words": FICTION_ANSWER_WORDS,
            "quote_target": FICTION_QUOTE_TARGET,
            "quote_max": FICTION_QUOTE_MAX,
            "rounds": FICTION_SAMPLE_ROUNDS,
        }
    return {
        "kind": NONFICTION,
        "system": technical_system(TECHNICAL_ANSWER_WORDS),
        "system_plain": SYSTEM_ANSWER,
        "gloss_system": answer_gloss_system(TECHNICAL_ANSWER_WORDS),
        "compare_system": compare_system(TECHNICAL_ANSWER_WORDS),
        "followup_system": followup_gloss_system(TECHNICAL_ANSWER_WORDS),
        "passage_limit": NONFICTION_PASSAGE_LIMIT,
        "options": _token_cap(TECHNICAL_ANSWER_WORDS, GENERATION_OPTIONS),
        "keep_body": False,
        "answer_words": TECHNICAL_ANSWER_WORDS,
        "quote_target": 1,
        "quote_max": 1,
        "rounds": 1,
    }
