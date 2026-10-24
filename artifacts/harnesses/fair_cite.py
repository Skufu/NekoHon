"""Fair citation judging, shared by the harnesses.

The rule: a citation is correct when the passage it points at answers the
question. Identity (this exact chunk, this exact chapter) is a note, not a
gate, unless the item says the identity is the behaviour under test.

Why: on 2026-10-24 the ask battery required the first citation to equal one
stored chunk. Four of ten pins were not the top-ranked passage, and a model
that always quotes the top-ranked passage failed exactly those four. The
battery was measuring agreement with a 2026-10-12 pick, not correctness.

Stdlib only.
"""

import re

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s|]+")


def fold(text):
    """Lowercase, collapse whitespace, drop punctuation except the term `|`."""
    return _WS_RE.sub(" ", _NONWORD_RE.sub(" ", (text or "").lower())).strip()


def missing_terms(terms, text):
    """Terms (regex, case-insensitive) that the text does not contain."""
    folded_text = fold(text)
    folded_terms = [fold(term) or (term or "") for term in terms or []]
    return [term for term in folded_terms if not re.search(term, folded_text)]


def passage_text(index, chunk_id):
    """The stored text for a chunk id, or '' when the id is not in the index."""
    for chunk in (index or {}).get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return chunk.get("text") or ""
    return ""


def text_lookup(index):
    """A chunk_id -> text callable, built once per index."""
    table = {
        chunk.get("chunk_id"): (chunk.get("text") or "")
        for chunk in (index or {}).get("chunks", [])
    }
    return lambda chunk_id: table.get(chunk_id, "")


def judge_citation(cited_ids, text_of, terms):
    """(ok, detail) for one answer's citations.

    ok when at least one cited passage contains every term. `terms` empty means
    there is no content signal, so the citation is accepted and the caller is
    expected to say so in its notes.
    """
    cited_ids = [cid for cid in (cited_ids or []) if cid]
    if not cited_ids:
        return False, "no citations"
    if not terms:
        return True, "no content terms; citation accepted"
    checked = []
    for chunk_id in cited_ids:
        missing = missing_terms(terms, text_of(chunk_id))
        if not missing:
            return True, f"{chunk_id} carries {terms}"
        checked.append(f"{chunk_id} misses {missing}")
    return False, "no cited passage carries all of " + str(list(terms)) + "; " + "; ".join(checked)


def judge_chapter(cited_chapters, expected_chapter, allowed_chapters, cited_text, terms):
    """(ok, detail) for a chapter expectation, with a content escape.

    The chapter is the behaviour under test when the item names one. A grounded
    answer that cites a different chapter still passes when the cited passages
    carry the turn's required concepts, because the reader got the content.
    """
    cited = [str(chapter) for chapter in cited_chapters or [] if chapter is not None]
    if expected_chapter is not None:
        if any(chapter == str(expected_chapter) for chapter in cited):
            return True, "expected chapter cited"
        if not cited:
            return False, f"no chapter cited, expected Ch. {expected_chapter}"
        missing = missing_terms(terms, cited_text) if terms else ["(no content terms)"]
        if not missing:
            return True, f"cited {cited} instead of Ch. {expected_chapter}, but the passage carries {terms}"
        return False, f"cited chapter(s) {cited} != expected Ch. {expected_chapter}"
    allowed = [str(chapter) for chapter in (allowed_chapters or [])]
    if allowed:
        if any(chapter in allowed for chapter in cited):
            return True, "allowed chapter cited"
        if not cited:
            return False, f"no chapter cited, expected one of Ch. {allowed}"
        missing = missing_terms(terms, cited_text) if terms else ["(no content terms)"]
        if not missing:
            return True, f"cited {cited} outside {allowed}, but the passage carries {terms}"
        return False, f"cited chapter(s) {cited} not in allowed chapters {allowed}"
    return True, "no chapter expectation"
