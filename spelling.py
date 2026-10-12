"""One-word typo repair for the question text the model sees. Post-v1 step 2.

Two repair paths (artifacts/post-v1-plan.md step 2, amended 2026-10-12):
- the prompt repair uses only words of the top passage; search already found
  the chunk (CRU, ET),
- the retry repair lets the whole book pick the word when search itself was
  misled (atermark); the caller must prove the retry retrieves strictly
  better passages before using it.

Both paths refuse ties, sub-cutoff matches, and real book words.
"""

import difflib
import re

CUTOFF = 0.85
WORD = re.compile(r"[A-Za-z]+")


def book_spellings(index):
    """Folded word -> the spelling used in the book, first occurrence."""
    spellings = {}
    for chunk in index.get("chunks") or []:
        for match in WORD.finditer(chunk.get("text") or ""):
            spellings.setdefault(match.group().lower(), match.group())
    return spellings


def _ranked(folded, candidates):
    return sorted(
        (
            (difflib.SequenceMatcher(None, folded, candidate).ratio(), candidate)
            for candidate in candidates
        ),
        reverse=True,
    )


def _only_candidate(folded, candidates):
    """The single candidate within CUTOFF. Two or more within it: none."""
    within = [
        candidate
        for score, candidate in _ranked(folded, candidates)
        if score >= CUTOFF
    ]
    if len(within) != 1:
        return None
    return within[0]


def _clearest_candidate(folded, candidates):
    """The strictly closest candidate within CUTOFF. A tie at the top: none."""
    ranked = _ranked(folded, candidates)
    if not ranked or ranked[0][0] < CUTOFF:
        return None
    if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
        return None
    return ranked[0][1]


def _apply(question, fixes):
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


def correct_question(question, index, passages):
    """Prompt repair. Candidates come from the top passage only.

    Search already found the chunk; this changes the prompt text only.
    Unchanged otherwise.
    """
    if not passages:
        return question
    top_spellings = {}
    for match in WORD.finditer(passages[0].get("text") or ""):
        top_spellings.setdefault(match.group().lower(), match.group())
    known = book_spellings(index)
    fixes = []
    for match in WORD.finditer(question):
        folded = match.group().lower()
        if folded in known:
            continue
        candidate = _only_candidate(folded, top_spellings)
        if candidate is None:
            continue
        fixes.append((match.start(), match.end(), top_spellings[candidate]))
    return _apply(question, fixes)


def book_repair(question, index):
    """Retry repair. The whole book picks the word; unique best only.

    The caller re-searches with the repaired question and keeps the result
    only when the top score strictly improves. Unchanged otherwise.
    """
    known = book_spellings(index)
    fixes = []
    for match in WORD.finditer(question):
        folded = match.group().lower()
        if folded in known:
            continue
        candidate = _clearest_candidate(folded, known)
        if candidate is None:
            continue
        fixes.append((match.start(), match.end(), known[candidate]))
    return _apply(question, fixes)
