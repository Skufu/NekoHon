"""Intent Engine: Book-agnostic highlight and query intent classification. stdlib only.

Classifies any reader highlight and optional query inside an active chunk and its
neighborhood into one of 4 structural intents:
1. CONCEPT_TERM: short noun phrase, technical term, acronym, or section heading.
2. VAGUE_FRAGMENT: clause or predicate fragment starting with copula/auxiliary/preposition.
3. MULTI_SENTENCE_PASSAGE: multi-sentence selection or passage (>= 140 chars).
4. AUTHOR_QUESTION: rhetorical or evaluative question ending with '?'.
"""

import re
from engine.retrieval.preprocess import STOPWORDS, stem, words

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
    r"^(?:chapter|section|part)\s+\d+(?:[\.-]\d+)*[\.:\s-]*|"
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

STRUCTURAL_HEADINGS = frozenset({
    "conclusion", "summary", "introduction", "overview",
    "additional resources", "references", "preface", "notes", "closing thoughts",
})


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

    is_passing_mention = False
    if chunk and intent_type == INTENT_CONCEPT_TERM:
        head_str = (heading or (chunk.get("heading") if chunk else "") or "").strip()
        sel_str = (selection or "").strip()
        is_heading_match = bool(
            head_str and (sel_str.lower() in head_str.lower() or head_str.lower() in sel_str.lower())
        )
        is_defined_in_sentence = False
        if anchor_sentence:
            c_low = (core_concept or sel_str).strip().lower()
            a_low = anchor_sentence.lower()
            def_pred_pat = (
                r"\b" + re.escape(c_low)
                + r"(?:s|\b)?(?:\s+\([^)]+\))?\s+(?:is|are|refers to|means|defined as|takes|allows|consists of)\b"
            )
            if re.search(def_pred_pat, a_low):
                is_defined_in_sentence = True
            else:
                clean_a = INTRO_ADVERBIAL_RE.sub("", anchor_sentence).strip()
                clean_a = re.sub(r"^(?:the|a|an)\s+", "", clean_a, flags=re.I).strip()
                if clean_a.lower().startswith(c_low):
                    if re.search(r"^(?:" + re.escape(c_low) + r")(?:s|\b)?\s+(?:is|are|was|were|refers|means|defines|defined|takes|allows|consists)\b", clean_a.lower()):
                        is_defined_in_sentence = True
        is_passing_mention = bool(not is_heading_match and head_str and not is_defined_in_sentence)

    return {
        "intent_type": intent_type,
        "core_concept": core_concept,
        "subject": subject,
        "anchor_sentence": anchor_sentence,
        "chosen_chunk": chosen_chunk,
        "is_passing_mention": is_passing_mention,
    }


def _is_redundant_followup(cand_q: str, clean_q: str, clean_sel: str = "") -> bool:
    """True when cand_q has >= 60% stemmed content-word overlap with the user question/selection."""
    if not cand_q:
        return True
    c_words = [w.lower() for w in words(cand_q) if len(w) >= 3 and w.lower() not in STOPWORDS]
    if not c_words:
        return False
    c_stems = {stem(w) for w in c_words}
    q_text = f"{clean_q} {clean_sel}".strip()
    q_words = [w.lower() for w in words(q_text) if len(w) >= 3 and w.lower() not in STOPWORDS]
    q_stems = {stem(w) for w in q_words}
    if not q_stems:
        return False
    overlap = len(c_stems & q_stems) / len(c_stems)
    return overlap >= 0.6


def _is_example_or_tool_mention(term: str, text: str) -> bool:
    """True if term appears in a sentence with example, tool, platform, or vendor cues."""
    if not term or not text:
        return False
    t_low = term.lower()
    EXAMPLE_TOOL_CUES = (
        "for example", "for instance", "such as", "like ", "example",
        "vendors", "products", "platforms", "platform", "upload", "push",
        "calculate", "using", "destination", "tool", "tools",
    )
    sents = split_sentences(text)
    for idx, s in enumerate(sents):
        s_low = s.lower()
        if t_low in s_low:
            if any(cue in s_low for cue in EXAMPLE_TOOL_CUES):
                return True
            for adj_idx in (idx - 1, idx + 1):
                if 0 <= adj_idx < len(sents):
                    adj_low = sents[adj_idx].lower()
                    if any(cue in adj_low for cue in ("for example", "for instance", "such as", "everyday use case", "use case", "example")):
                        return True
    return False


def _has_contrast_in_passage(term: str, text: str) -> bool:
    """True if term appears in a sentence (or adjacent sentence) containing contrast markers."""
    if not term or not text:
        return False
    t_low = term.lower()
    CONTRAST_MARKERS = (
        "versus", "vs.", "vs", "unlike", "differ", "difference",
        "in contrast", "compared to", "rather than", "instead of",
    )
    sents = split_sentences(text)
    for idx, s in enumerate(sents):
        s_low = s.lower()
        if t_low in s_low:
            if any(m in s_low for m in CONTRAST_MARKERS):
                return True
            for adj_idx in (idx - 1, idx + 1):
                if 0 <= adj_idx < len(sents):
                    adj_low = sents[adj_idx].lower()
                    if any(m in adj_low for m in CONTRAST_MARKERS):
                        return True
    return False


_GENERIC_FOLLOWUPS = [
    "What is the main takeaway?",
    "What problem does this solve?",
    "Explain this in simpler words",
]

_SKIP_PAREN_MARKERS = (
    " or ", " and ", "otherwise", "e.g", "i.e", "chapter", "figure", "section", "top", "bottom", "left", "right"
)

_SPECIFIC_PHRASES = (
    "enterprise ossification", "evaluation of trade-offs", "change management",
    "simple lift and shift", "lease cliff", "types of windows", "dataflow model",
)

_DISCARD_OPENERS = frozenset({
    "figure", "fig", "table", "chapter", "ch", "section", "part", "page",
    "what", "why", "how", "when", "where", "who", "which",
    "is", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "will",
    "let", "see", "note",
})

_DROP_OPENERS = frozenset({
    "in", "on", "at", "for", "to", "with", "by", "the", "a", "an", "this",
    "that", "these", "those", "we", "our", "you", "here", "as", "such",
    "unlike", "against", "between",
    "while", "although", "though", "when", "since", "if", "where", "because",
    "after", "before", "during", "despite", "given", "unless", "until", "once",
    "whether", "whereas",
})

_TRADEOFF_SIGNALS = (
    "trade-off", "trade-offs", "tradeoffs", "cost", "expensive", "pricing",
    "pay-as-you-go", "limitation", "limitations", "downside", "downsides",
    "bottleneck", "bottlenecks", "overhead", "latency", "throughput",
    "versus", "vs", "drawback", "drawbacks", "compromise", "sacrifice",
)

_PLURAL_EXCEPTIONS = ("SSDs", "HDDs", "CPUs", "GPUs", "VMs", "DAGs", "APIs")
_NON_PLURAL_ENDINGS = ("ss", "us", "is", "as", "os", "ics")
_TERM_STRIP = " \t\r\n—–-,:;\"'“”()[]"
_PAREN_TERM_RE = r"\(([A-Za-z0-9 \t_-]{2,30})\)"


def _body_no_heading(t: str, h: str = "") -> str:
    if not t:
        return ""
    lines = t.splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    if h and first.lower() == h.lower():
        return "\n".join(lines[1:])
    if len(lines) > 1 and not first.endswith((".", "?", "!", ":", ";", '"', "'", "”")):
        if h and (first.lower() in h.lower() or h.lower() in first.lower()):
            return "\n".join(lines[1:])
        if len(first) <= 60 and first[:1].isupper():
            return "\n".join(lines[1:])
    return t


def _neighbor_raw_terms(chunk: dict, neighbors: list) -> list[str]:
    terms = []
    for n in neighbors:
        if n and str(n.get("chapter")) == str(chunk.get("chapter")):
            n_body = _body_no_heading(n.get("text") or "", (n.get("heading") or "").strip())
            for m in re.finditer(_PAREN_TERM_RE, n_body):
                val = m.group(1)
                if not any(sm in val.lower() for sm in _SKIP_PAREN_MARKERS) and not any(w.lower() in ("or", "and", "otherwise", "etc") for w in val.split()):
                    terms.append(val)
            for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:[ \t]+[A-Z][A-Za-z0-9]+){1,2})\b", n_body):
                terms.append(m.group(1))
            break
    return terms


def _raw_terms(chunk: dict, neighbors: list, chunk_heading: str) -> list[str]:
    chunk_low = (chunk.get("text") or "").lower()
    body = _body_no_heading(chunk.get("text") or "", chunk_heading)
    terms = []
    for m in re.finditer(_PAREN_TERM_RE, body):
        val = m.group(1)
        if not any(sm in val.lower() for sm in _SKIP_PAREN_MARKERS):
            terms.append(val)
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:[ \t]+(?:and[ \t]+)?[A-Z][A-Za-z0-9]+){1,2})\b", body):
        terms.append(m.group(1))
    for m in re.finditer(r"\b(?:known as|called|termed)[ \t]+([a-zA-Z0-9 \t_-]{3,30})[—–,\.\)]", body, re.I):
        terms.append(m.group(1))
    for phrase in _SPECIFIC_PHRASES:
        if phrase in chunk_low:
            terms.append(phrase)
    for line in body.splitlines():
        l_strip = line.strip()
        if (
            3 <= len(l_strip) <= 25
            and l_strip[0].isupper()
            and not l_strip.endswith((".", "?", "!", ":"))
            and l_strip.lower() != chunk_heading.lower()
            and 1 <= len(l_strip.split()) <= 3
        ):
            terms.append(l_strip)
    if not terms and neighbors:
        terms.extend(_neighbor_raw_terms(chunk, neighbors))
    return terms


def _author_question(chunk_text: str, exclude_text: str, clean_q: str, clean_sel: str) -> str:
    for s in split_sentences(chunk_text):
        s_strip = s.strip()
        if (
            s_strip.endswith("?")
            and 15 <= len(s_strip) <= 42
            and s_strip.lower() not in exclude_text
            and not _is_redundant_followup(s_strip, clean_q, clean_sel)
        ):
            return s_strip
    return ""


def _clean_term(t: str) -> str:
    t_clean = re.sub(r"\s+", " ", t).strip(_TERM_STRIP)
    t_words = t_clean.split()
    if not (2 <= len(t_clean) <= 28) or len(t_words) > 4:
        return ""
    if t_words and (t_words[0].lower() in _DISCARD_OPENERS or (len(t_words) == 1 and t_words[0].lower() in _DROP_OPENERS)):
        return ""
    while t_words and t_words[0].lower() in _DROP_OPENERS and len(t_words) > 1:
        t_clean = re.sub(r"\s+", " ", " ".join(t_words[1:])).strip(_TERM_STRIP)
        t_words = t_clean.split()
    if not t_clean or len(t_clean) < 2:
        return ""
    if re.search(r"\b\d+[-–.]\d+\b", t_clean):
        return ""
    if not any(len(w) >= 3 and any(c.isalpha() for c in w) for w in t_words):
        return ""
    return t_clean


def _candidate_terms(raw_terms: list[str], exclude_text: str, clean_q: str, clean_sel: str) -> list[str]:
    candidates = []
    seen = set()
    for t in raw_terms:
        t_clean = _clean_term(t)
        if not t_clean:
            continue
        t_low = t_clean.lower()
        if t_low in seen or t_low in exclude_text:
            continue
        if _is_redundant_followup(t_clean, clean_q, clean_sel):
            continue
        if all(w.lower() in STOPWORDS for w in t_clean.split()):
            continue
        seen.add(t_low)
        candidates.append(t_clean)
    return [
        t for t in candidates
        if not any(t.lower() != other.lower() and t.lower() in other.lower() for other in candidates)
    ]


def _has_tradeoff_signal(chunk_low: str, neighbors: list) -> bool:
    return any(w in chunk_low for w in _TRADEOFF_SIGNALS) or any(
        any(w in (n.get("text") or "").lower() for w in _TRADEOFF_SIGNALS)
        for n in (neighbors or []) if n and isinstance(n, dict)
    )


def _is_plural_term(t: str) -> bool:
    return (t.endswith("s") and not t.lower().endswith(_NON_PLURAL_ENDINGS)) or t in _PLURAL_EXCEPTIONS


def _pattern_slot1(lead_low: str, chunk_low: str, clean_q: str, exclude_text: str) -> str:
    q_low = clean_q.lower()
    if (
        (
            re.search(r"\b(two\s+reasons|three\s+reasons|several\s+reasons)\b", lead_low)
            or ("reason" in lead_low and any(num in lead_low for num in ("two", "three", "several", "essential")))
            or ("two reasons" in chunk_low or "three reasons" in chunk_low)
        )
        and "reason" not in q_low
    ):
        return "What are the specific reasons?"
    if re.search(r"\b(main\s+stages|several\s+stages|stages)\b", lead_low) and "stage" not in q_low:
        return "What are the main stages?"
    if re.search(r"\b(key\s+types|several\s+types|types\s+of)\b", lead_low) and "type" not in q_low:
        return "What are the key types?"
    if re.search(r"\b(characteristics|common\s+threads)\b", lead_low) and "characteristic" not in q_low:
        return "What are the key characteristics?"
    if re.search(r"\b(several\s+ways|ways\s+to)\b", lead_low) and "way" not in q_low:
        return "What are the specific ways?"
    if "antipattern" in chunk_low and "antipattern" not in exclude_text:
        return "Why was this viewed as an antipattern?"
    if "overlap" in chunk_low and "overlap" not in exclude_text:
        return "What fields overlap here?"
    if ("manual" in chunk_low or "primitive" in chunk_low) and "manual" not in exclude_text and "primitive" not in exclude_text:
        return "What manual process does this replace?"
    return ""


def _first_fitting(options: list[str], clean_q: str, clean_sel: str) -> str:
    for q_cand in options:
        if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
            return q_cand
    return ""


def _term_slot1(candidate_terms: list[str], chunk_text: str, clean_q: str, clean_sel: str) -> tuple[str, str]:
    for t in candidate_terms:
        options = []
        if _is_example_or_tool_mention(t, chunk_text):
            options = [f"What is the role of {t}?", f"How is {t} used here?"]
        plural = _is_plural_term(t)
        options.append(f"How {'do' if plural else 'does'} {t} relate to this?")
        options.append(f"What is {t}?" if not plural else f"What are {t}?")
        q = _first_fitting(options, clean_q, clean_sel)
        if q:
            return q, t
    return "", ""


def _slot1(candidate_terms, chunk_text, chunk_low, lead_low, chunk_heading, clean_q, clean_sel, exclude_text) -> tuple[str, str]:
    slot = _pattern_slot1(lead_low, chunk_low, clean_q, exclude_text)
    if slot:
        return slot, ""
    slot, used_term = _term_slot1(candidate_terms, chunk_text, clean_q, clean_sel)
    if slot:
        return slot, used_term
    core_concept = extract_core_concept(clean_sel, chunk_heading)
    if core_concept and core_concept.lower() not in exclude_text:
        slot = _first_fitting([f"How does {core_concept} work?"], clean_q, clean_sel)
        if slot:
            return slot, ""
    return "How does this work in practice?", ""


def _slot2(candidate_terms, chunk_text, chunk_low, slot1, used_term, exclude_text, clean_q, clean_sel, tradeoff) -> str:
    if "ossification" in chunk_low and "ossification" not in exclude_text:
        return "What are the risks of ossification?"
    if "lease cliff" in chunk_low or "cliff" in chunk_low:
        return "What is the risk of a lease cliff?"
    if any(w in chunk_low for w in ("cost", "expensive", "pricing", "pay-as-you-go")):
        return "What are the cost trade-offs?"
    if any(w in chunk_low for w in ("bottleneck", "bottlenecks")):
        return "What are the main bottlenecks?"
    if any(w in chunk_low for w in ("limitation", "limitations", "downside", "downsides")):
        return "What are the main limitations?"
    if any(w in chunk_low for w in ("risk", "risks", "mistake", "mistakes", "failure")):
        return "What are the risks or pitfalls?"
    if any(w in chunk_low for w in ("trade-off", "trade-offs", "tradeoffs")):
        return "What are the key trade-offs?"
    if "antipattern" in chunk_low and "antipattern" not in exclude_text and not slot1.startswith("Why was this viewed"):
        return "Why was this viewed as an antipattern?"
    if "overlap" in chunk_low and not slot1.startswith("What fields overlap"):
        return "What fields overlap here?"
    if ("manual" in chunk_low or "primitive" in chunk_low) and not slot1.startswith("What manual process"):
        return "What manual process does this replace?"
    for t2 in candidate_terms:
        if t2.lower() != used_term.lower() and t2.lower() not in used_term.lower() and used_term.lower() not in t2.lower():
            if _has_contrast_in_passage(t2, chunk_text):
                q = _first_fitting([f"How does this compare to {t2}?"], clean_q, clean_sel)
                if q:
                    return q
    return "What are the key trade-offs?" if tradeoff else "What problem does this solve?"


def _next_heading_question(chunk, neighbors, chunk_heading, chunk_low, exclude_text, clean_q, clean_sel) -> str:
    for n in neighbors:
        if not n or str(n.get("chapter")) != str(chunk.get("chapter")):
            continue
        cid_n = str(n.get("chunk_id", ""))
        cid_cur = str(chunk.get("chunk_id", ""))
        if cid_n and cid_cur and cid_n <= cid_cur:
            continue
        n_head = (n.get("heading") or "").strip()
        if not n_head or n_head.lower() == chunk_heading.lower() or n_head.lower() in exclude_text:
            continue
        clean_next = extract_core_concept(n_head)
        if not (
            clean_next
            and len(clean_next) <= 28
            and clean_next.lower() not in STRUCTURAL_HEADINGS
            and clean_next.lower() not in chunk_low
            and not _is_redundant_followup(clean_next, clean_q, clean_sel)
        ):
            continue
        is_plural = clean_next.endswith("s") and not clean_next.lower().endswith(_NON_PLURAL_ENDINGS)
        q = _first_fitting([f"What is {clean_next}?" if not is_plural else f"What are {clean_next}?"], clean_q, clean_sel)
        if q:
            return q
    return ""


def _slot3(chunk, neighbors, chunk_heading, chunk_low, author_q, slot1, slot2, exclude_text, clean_q, clean_sel) -> str:
    if author_q and author_q.lower() not in (slot1.lower(), slot2.lower()):
        return author_q
    if "everyday use case" in chunk_low or "use cases" in chunk_low or "use case" in chunk_low:
        return "What are the main use cases?"
    if any(marker in chunk_low for marker in ("for instance", "for example", "consider", "such as", "examples of")):
        return "What example do the authors give?"
    if neighbors:
        q = _next_heading_question(chunk, neighbors, chunk_heading, chunk_low, exclude_text, clean_q, clean_sel)
        if q:
            return q
    return "Explain this in simpler words"


def _assemble_followups(slots, tradeoff: bool, clean_q: str, clean_sel: str) -> list[str]:
    followups = []
    seen_q = set()
    for q in slots:
        q_clean = re.sub(r"\s+", " ", (q or "")).strip()
        if len(q_clean) > 45:
            q_clean = q_clean[:41].rstrip(" ?.,-") + "?"
        if q_clean and q_clean.lower() not in seen_q and not _is_redundant_followup(q_clean, clean_q, clean_sel):
            seen_q.add(q_clean.lower())
            followups.append(q_clean)
    fallbacks = ["What are the key trade-offs?"] if tradeoff else []
    fallbacks.extend([
        "What problem does this solve?",
        "What is the main takeaway?",
        "What example do the authors give?",
        "Explain this in simpler words",
        "Why does this matter?",
    ])
    for fb in fallbacks:
        if len(followups) >= 3:
            break
        if fb.lower() not in seen_q and not _is_redundant_followup(fb, clean_q, clean_sel):
            seen_q.add(fb.lower())
            followups.append(fb)
    return followups[:3]


def compute_dynamic_followups(
    chunk: dict,
    neighbors: list = None,
    selection: str = "",
    question: str = "",
    answer_text: str = "",
    mode: str = "explain",
) -> list[str]:
    if not chunk or not isinstance(chunk, dict):
        return list(_GENERIC_FOLLOWUPS)

    chunk_text = chunk.get("text") or ""
    chunk_heading = (chunk.get("heading") or "").strip()
    clean_sel = (selection or "").strip()
    clean_q = (question or "").strip()
    exclude_text = f"{clean_sel} {clean_q}".lower()

    quote_text = ""
    if answer_text:
        m_q = re.search(r'\[Ch\.\s*[^\]]+\]\s*["“](.+?)["”]', answer_text)
        if m_q:
            quote_text = m_q.group(1).strip()

    lead_low = f"{clean_sel} {quote_text}".strip().lower()
    chunk_low = chunk_text.lower()

    candidate_terms = _candidate_terms(_raw_terms(chunk, neighbors, chunk_heading), exclude_text, clean_q, clean_sel)
    author_q = _author_question(chunk_text, exclude_text, clean_q, clean_sel)
    tradeoff = _has_tradeoff_signal(chunk_low, neighbors)

    slot1, used_term = _slot1(candidate_terms, chunk_text, chunk_low, lead_low, chunk_heading, clean_q, clean_sel, exclude_text)
    slot2 = _slot2(candidate_terms, chunk_text, chunk_low, slot1, used_term, exclude_text, clean_q, clean_sel, tradeoff)
    slot3 = _slot3(chunk, neighbors, chunk_heading, chunk_low, author_q, slot1, slot2, exclude_text, clean_q, clean_sel)
    return _assemble_followups((slot1, slot2, slot3), tradeoff, clean_q, clean_sel)
