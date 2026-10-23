import functools
import re

from engine.answering.glossclean import fix_acronym_casing
from engine.answering.intent import META_TRANSITION_RE, extract_core_concept, select_substantive_anchor_sentence
from engine.answering.sentences import candidate_sentences
from engine.retrieval.preprocess import STOPWORDS


_WORD_RE = re.compile(r"\w+")


_ENTITY_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:[- ](?:[A-Z0-9][a-zA-Z0-9]*|\d+(?:\.\d+)*))+)\b")


_ACRONYM_MATCH_RE = re.compile(r"\b([A-Z]{2,10}s?)\b")


_STRIP_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")


_QUESTION_STARTERS = frozenset({
    "what", "why", "how", "when", "where", "who", "which",
    "is", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "will", "explain",
    "describe", "define", "chapter", "section", "figure",
    "regarding", "about", "compare", "contrast", "differentiate",
    "distinguish", "versus", "vs",
})


_GENERIC_ENTITY_WORDS = frozenset({
    "type", "types", "kind", "kinds", "level", "levels", "stage", "stages",
    "phase", "phases", "step", "steps", "chapter", "chapters", "section", "sections",
    "table", "tables", "figure", "figures", "part", "parts",
})


@functools.lru_cache(maxsize=512)
def _selection_word_pattern(sel):
    return re.compile(rf"\b{re.escape(sel)}\b", re.IGNORECASE)


FRAMING_WORDS = frozenset((
    "define", "defines", "defined", "definition",
    "describe", "describes", "described", "description",
    "explain", "explains", "explained", "explanation",
    "mean", "means", "meaning",
    "stand", "stands",
    "constitute", "constitutes",
    "refer", "refers",
    "work", "works", "worked", "working",
    "occur", "occurs", "occurred",
    "use", "uses", "used", "using",
    "handle", "handles", "handled", "handling",
    "require", "requires", "required", "requirement", "requirements",
    "condition", "conditions",
    "provide", "provides", "provided",
    "complete", "completes", "completed", "completing",
    "achieve", "achieves", "achieved",
    "perform", "performs", "performed",
))


def extract_query_entities(q: str, heading: str = "") -> list[str]:
    if not q:
        return []
    normalized_q = fix_acronym_casing(q)
    entities = []
    for m in _ENTITY_PHRASE_RE.finditer(normalized_q):
        val = m.group(1).strip()
        parts = val.split()
        while parts and parts[0].lower() in _QUESTION_STARTERS:
            parts = parts[1:]
        if len(parts) >= 2:
            val = " ".join(parts)
            if val.lower() not in STOPWORDS:
                entities.append(val)
        elif len(parts) == 1 and parts[0].lower() not in STOPWORDS and parts[0].lower() not in _QUESTION_STARTERS and parts[0].lower() not in _GENERIC_ENTITY_WORDS:
            entities.append(parts[0])
    for m in _ACRONYM_MATCH_RE.finditer(normalized_q):
        val = m.group(1).strip()
        if val.lower() not in STOPWORDS and val not in entities:
            entities.append(val)
    words_list = normalized_q.split()
    for w in words_list:
        w_clean = _STRIP_PUNCT_RE.sub("", w)
        if (
            w_clean
            and w_clean[0].isupper()
            and w_clean.lower() not in STOPWORDS
            and w_clean.lower() not in FRAMING_WORDS
            and w_clean.lower() not in _QUESTION_STARTERS
            and w_clean.lower() not in _GENERIC_ENTITY_WORDS
        ):
            if not any(w_clean in ent for ent in entities):
                entities.append(w_clean)
    head_low = heading.lower() if heading else ""
    return [e for e in entities if not head_low or e.lower() not in head_low]


def clean_selection_text(sel: str) -> str:
    raw = (sel or "").strip()
    if not raw:
        return ""
    if "\n" in raw:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2 and len(lines[0]) <= 40 and lines[0].endswith(":"):
            raw = " ".join(lines[1:])
    return re.sub(r"\s+", " ", raw).strip()


def anchor_sentence_for_selection(chunk, selection):
    text = chunk.get("text") or ""
    heading = chunk.get("heading") or ""
    sel = (selection or "").strip()
    if not sel:
        return None
    cands = candidate_sentences(text, heading)
    if not cands:
        return None

    word_pat = _selection_word_pattern(sel)
    matched = [s for s in cands if word_pat.search(s)]

    if not matched:
        matched = [s for s in cands if sel.lower() in s.lower()]

    if not matched:
        sel_words = set(_WORD_RE.findall(sel.lower()))
        if sel_words:
            cand_words = {s: set(_WORD_RE.findall(s.lower())) for s in cands}
            scored_cands = sorted(
                cands,
                key=lambda s: len(sel_words & cand_words[s]),
                reverse=True,
            )
            if scored_cands and (sel_words & cand_words[scored_cands[0]]):
                matched = [scored_cands[0]]

    if not matched:
        if heading and (sel.lower() in heading.lower() or word_pat.search(heading)):
            long_cands = [s for s in cands if len(s) >= 40 and not META_TRANSITION_RE.search(s)]
            if long_cands:
                return long_cands[0]
            _, sub = select_substantive_anchor_sentence(chunk, [], sel, extract_core_concept(sel, heading))
            return sub if sub else (cands[0] if cands else None)
        return None

    best = matched[0]
    for m in matched:
        if len(m) >= 40 and not META_TRANSITION_RE.search(m):
            best = m
            break

    if META_TRANSITION_RE.search(best) or (heading and (sel.lower() in heading.lower() or word_pat.search(heading))):
        _, sub = select_substantive_anchor_sentence(chunk, [], sel, extract_core_concept(sel, heading))
        if sub and not META_TRANSITION_RE.search(sub):
            best = sub

    if len(best) < 40 or best.endswith("?"):
        idx = cands.index(best) if best in cands else 0
        expanded = best
        fwd = idx + 1
        while len(expanded) < 40 and fwd < len(cands):
            expanded = expanded + " " + cands[fwd]
            fwd += 1
        bwd = idx - 1
        while len(expanded) < 40 and bwd >= 0:
            expanded = cands[bwd] + " " + expanded
            bwd -= 1
        if len(expanded) >= 40:
            best = expanded

    return best
