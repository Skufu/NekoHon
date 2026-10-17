"""Intent Engine: Book-agnostic highlight and query intent classification. stdlib only.

Classifies any reader highlight and optional query inside an active chunk and its
neighborhood into one of 4 structural intents:
1. CONCEPT_TERM: short noun phrase, technical term, acronym, or section heading.
2. VAGUE_FRAGMENT: clause or predicate fragment starting with copula/auxiliary/preposition.
3. MULTI_SENTENCE_PASSAGE: multi-sentence selection or passage (>= 140 chars).
4. AUTHOR_QUESTION: rhetorical or evaluative question ending with '?'.
"""

import re
from preprocess import STOPWORDS, words

INTENT_CONCEPT_TERM = "CONCEPT_TERM"
INTENT_VAGUE_FRAGMENT = "VAGUE_FRAGMENT"
INTENT_MULTI_SENTENCE = "MULTI_SENTENCE_PASSAGE"
INTENT_AUTHOR_QUESTION = "AUTHOR_QUESTION"

COPULA_AUX_PREP = frozenset({
    "is", "are", "was", "were", "be", "been",
    "has", "have", "had",
    "can", "could", "will", "would", "should", "may", "might", "must",
    "does", "do", "did",
    "to", "for", "with", "by", "in", "on", "at", "from", "as", "than", "that", "which",
})

META_TRANSITION_RE = re.compile(
    r"\b(before we (?:discuss|explore|look|dive|examine)|"
    r"it(?:'s| is) helpful to pause|"
    r"in this (?:section|chapter)|"
    r"we will (?:discuss|explore|cover|look at)|"
    r"let(?:'s| us) (?:pause|take a look|turn to|begin by))\b",
    re.IGNORECASE,
)

CORE_PREFIX_RE = re.compile(
    r"^(?:an?|the)\s+(?:brief\s+|quick\s+|short\s+)?(?:detour|note|primer|introduction|intro|overview|look|word|section|chapter|guide|discussion|summary|background|thoughts?)\s+(?:on|to|about|of|for)\s+|"
    r"^(?:brief\s+|quick\s+|short\s+)?(?:detour|note|primer|introduction|intro|overview|look|word|section|chapter|guide|discussion|summary|background|thoughts?)\s+(?:on|to|about|of|for)\s+|"
    r"^(?:understanding|defining|exploring|what\s+is|what\s+are)\s+",
    re.IGNORECASE,
)

DEFINITIONAL_PREDICATE_RE = re.compile(
    r"\b(is|are|refers to|means|defined as|involves|focuses on|make money|pricing|cost|pay-as-you-go|opex|capex|optimize|efficiency)\b",
    re.IGNORECASE,
)

EVALUATIVE_PREDICATE_RE = re.compile(
    r"\b(reasonable\s+strategy|rude\s+shock|on\s+(?:its|their|the)\s+head|good\s+idea|bad\s+idea|makes?\s+sense|best\s+practice)\b",
    re.IGNORECASE,
)

INTRO_ADVERBIAL_RE = re.compile(
    r"^(?:in addition|however|furthermore|moreover|for example|for instance|recall that|note that|in general|on the other hand|similarly|finally|first|second|third|meanwhile|specifically|also|as a result),?\s*",
    re.IGNORECASE,
)


def extract_core_concept(selection: str, heading: str = "") -> str:
    """Extract substantive core concept from a highlight or heading by stripping structural prefixes."""
    text = (selection or "").strip().strip("\"'“”")
    if not text and heading:
        text = heading.strip().strip("\"'“”")
    if not text:
        return ""
    for _ in range(2):
        cleaned = CORE_PREFIX_RE.sub("", text).strip()
        if cleaned == text:
            break
        text = cleaned
    text = text.strip(" \t\r\n:;.,?!")
    return text


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, honoring paragraph and sentence boundaries."""
    raw = (text or "").strip()
    if not raw:
        return []
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    cands = []
    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines() if line.strip()]
        if not lines:
            continue
        body_lines = []
        for i, line in enumerate(lines):
            if i == 0 and len(lines) > 1 and not line.endswith((".", "?", "!", ":", ";", '"', "'", "”")):
                if len(line) >= 40:
                    cands.append(line)
            else:
                body_lines.append(line)
        if body_lines:
            body_text = " ".join(body_lines)
            parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body_text) if s.strip()]
            cands.extend(parts)
    return cands


def classify_intent(selection: str, heading: str = "", chunk: dict = None) -> str:
    """Classify the highlight into CONCEPT_TERM, VAGUE_FRAGMENT, MULTI_SENTENCE_PASSAGE, or AUTHOR_QUESTION."""
    sel = (selection or "").strip()
    if not sel:
        return INTENT_CONCEPT_TERM

    # 1. Author question: ends with '?'
    if sel.endswith("?"):
        return INTENT_AUTHOR_QUESTION

    # 2. Multi-sentence passage: >= 140 chars or 2+ distinct sentences
    sents = [s for s in re.split(r"(?<=[.!?])\s+", sel) if len(s.strip()) > 10]
    if len(sel) >= 140 or len(sents) >= 2:
        return INTENT_MULTI_SENTENCE

    # 3. Vague fragment: clause/predicate fragment (2–10 words) starting with copula/aux/prep
    # or containing an evaluative predicate
    sel_words = sel.split()
    word_count = len(sel_words)
    if 2 <= word_count <= 10:
        first_word = re.sub(r"^\W+", "", sel_words[0]).lower()
        if first_word in COPULA_AUX_PREP or EVALUATIVE_PREDICATE_RE.search(sel):
            return INTENT_VAGUE_FRAGMENT

    # 4. Concept term: short noun phrase/term/acronym (1-6 words) or in heading
    head = (heading or (chunk.get("heading") if chunk else "") or "").strip().lower()
    if head and (sel.lower() in head or head in sel.lower()):
        return INTENT_CONCEPT_TERM
    if word_count <= 6:
        return INTENT_CONCEPT_TERM

    return INTENT_MULTI_SENTENCE if len(sel) >= 100 else INTENT_CONCEPT_TERM


def extract_enclosing_subject(sentence: str, selection: str) -> str:
    """Find selection inside sentence and extract the grammatical subject before it."""
    if not sentence or not selection:
        return ""
    m = re.search(re.escape(selection.strip()), sentence, re.IGNORECASE)
    if not m:
        pat = re.escape(selection.strip())
        pat = re.sub(r"\\\s+", r"\\s+", pat)
        m = re.search(pat, sentence, re.IGNORECASE)
    if not m:
        return ""

    before = sentence[:m.start()].strip()
    before = INTRO_ADVERBIAL_RE.sub("", before).strip()
    before = before.rstrip(" \t\r\n—–-,:;")
    before = before.lstrip(" \t\r\n—–-,:;")
    return before.strip()


def select_substantive_anchor_sentence(chunk: dict, neighbors: list, selection: str, core_concept: str = "") -> tuple[dict, str]:
    """Select the most substantive definitional anchor sentence, rejecting meta-transition sentences."""
    if not chunk:
        return {}, ""

    c_concept = core_concept or extract_core_concept(selection, chunk.get("heading", ""))
    concept_words = [w.lower() for w in words(c_concept) if w.lower() not in STOPWORDS and len(w) >= 3]

    def score_sentence(s: str) -> int:
        score = 0
        is_meta = bool(META_TRANSITION_RE.search(s))
        if is_meta:
            score -= 6
        s_lower = s.lower()
        s_words = set(words(s_lower))

        has_full_concept = (c_concept.lower() in s_lower) or (bool(concept_words) and all(w in s_words for w in concept_words))
        if has_full_concept and not is_meta:
            score += 4

        has_def = bool(DEFINITIONAL_PREDICATE_RE.search(s))
        overlap = len(set(concept_words) & s_words) if concept_words else 0
        if has_def or (concept_words and overlap >= max(1, len(concept_words) - 1)):
            score += 3

        if selection.lower() in s_lower and not is_meta:
            score += 2
        return score

    chunk_heading = (chunk.get("heading") or "").strip().lower()
    cands_chunk = [s for s in split_sentences(chunk.get("text", "")) if len(s) >= 40 and s.strip().lower() != chunk_heading]

    scored_chunk = [(score_sentence(s), s) for s in cands_chunk]
    best_chunk_non_meta = [s for sc, s in scored_chunk if sc > 0 and not META_TRANSITION_RE.search(s)]

    next_chunk = None
    if neighbors:
        for n in neighbors:
            if n and n != chunk:
                next_chunk = n
                break

    if best_chunk_non_meta:
        best_chunk_non_meta.sort(key=lambda s: (score_sentence(s), len(s)), reverse=True)
        return chunk, best_chunk_non_meta[0]

    if next_chunk:
        next_heading = (next_chunk.get("heading") or "").strip().lower()
        cands_next = [s for s in split_sentences(next_chunk.get("text", "")) if len(s) >= 40 and s.strip().lower() != next_heading]
        scored_next = [(score_sentence(s), s) for s in cands_next if not META_TRANSITION_RE.search(s) and score_sentence(s) > 0]
        if scored_next:
            scored_next.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
            return next_chunk, scored_next[0][1]

    non_meta = [s for s in cands_chunk if not META_TRANSITION_RE.search(s)]
    if non_meta:
        non_meta.sort(key=len, reverse=True)
        return chunk, non_meta[0]

    return chunk, (cands_chunk[0] if cands_chunk else "")


def analyze_intent(selection: str, heading: str = "", chunk: dict = None, neighbors: list = None) -> dict:
    """Analyze reader selection and context to return complete structural intent metadata."""
    intent_type = classify_intent(selection, heading, chunk)
    core_concept = extract_core_concept(selection, heading)
    chosen_chunk = chunk
    anchor_sentence = ""
    subject = ""

    if chunk:
        if intent_type == INTENT_CONCEPT_TERM:
            chosen_chunk, anchor_sentence = select_substantive_anchor_sentence(chunk, neighbors or [], selection, core_concept)
        elif intent_type == INTENT_VAGUE_FRAGMENT:
            cands = [s for s in split_sentences(chunk.get("text", "")) if len(s) >= 40]
            matched = [s for s in cands if selection.lower() in s.lower()]
            if matched:
                anchor_sentence = matched[0]
                subject = extract_enclosing_subject(anchor_sentence, selection)
            else:
                chosen_chunk, anchor_sentence = select_substantive_anchor_sentence(chunk, neighbors or [], selection, core_concept)
                subject = extract_enclosing_subject(anchor_sentence, selection)
        elif intent_type == INTENT_MULTI_SENTENCE:
            cands = [s for s in split_sentences(chunk.get("text", "")) if len(s) >= 40]
            matched = [s for s in cands if s in selection or selection in s]
            if not matched:
                sel_content = [w.lower() for w in words(selection[:120]) if w.lower() not in STOPWORDS]
                scored = sorted(cands, key=lambda s: len(set(sel_content) & set(words(s.lower()))), reverse=True)
                matched = [scored[0]] if (scored and set(sel_content) & set(words(scored[0].lower()))) else []
            anchor_sentence = matched[0] if matched else (cands[0] if cands else selection[:100])
        elif intent_type == INTENT_AUTHOR_QUESTION:
            cands = [s for s in split_sentences(chunk.get("text", "")) if len(s) >= 20]
            matched = [s for s in cands if selection.strip().lower() in s.lower()]
            anchor_sentence = matched[0] if matched else selection.strip()

    return {
        "intent_type": intent_type,
        "core_concept": core_concept,
        "subject": subject,
        "anchor_sentence": anchor_sentence,
        "chosen_chunk": chosen_chunk,
    }
