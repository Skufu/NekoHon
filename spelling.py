"""One-word typo repair for the question text the model sees. Post-v1 step 2.

Search still runs on the raw question: retrieval keeps the right chunk at
rank 1 for the CRU and ET typos. Only the model gets the repair. Rules, from
artifacts/post-v1-plan.md:
- the word is not already in the book,
- exactly one book word within a tight difflib cutoff,
- that word appears in the top retrieved passage.
A tie, a book word, or a weak match is left alone.
"""

import difflib
import re

CUTOFF = 0.85
WORD = re.compile(r"[A-Za-z]+")


def book_words(index):
    """Every word of every chunk, lowercased. Rebuild per call: 0.03 s measured."""
    words = set()
    for chunk in index.get("chunks") or []:
        words.update(m.group().lower() for m in WORD.finditer(chunk.get("text") or ""))
    return words


def correct_question(question, index, passages):
    """The question with unambiguous one-word typos repaired.

    Only words of the top passage may be substituted. Unchanged otherwise.
    """
    if not passages:
        return question
    top_spellings = {}
    for match in WORD.finditer(passages[0].get("text") or ""):
        top_spellings.setdefault(match.group().lower(), match.group())
    known = book_words(index)
    fixes = []
    for match in WORD.finditer(question):
        folded = match.group().lower()
        if folded in known:
            continue
        ranked = sorted(
            (
                (difflib.SequenceMatcher(None, folded, candidate).ratio(), candidate)
                for candidate in top_spellings
            ),
            reverse=True,
        )
        nearest = [candidate for score, candidate in ranked if score >= CUTOFF]
        if len(nearest) != 1:
            continue
        fixes.append((match.start(), match.end(), top_spellings[nearest[0]]))
    if not fixes:
        return question
    parts = []
    cursor = 0
    for start, end, replacement in fixes:
        parts.append(question[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(question[cursor:])
    return "".join(parts)
