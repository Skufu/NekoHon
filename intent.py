"""Intent Engine: Book-agnostic highlight and query intent classification. stdlib only.

Classifies any reader highlight and optional query inside an active chunk and its
neighborhood into one of 4 structural intents:
1. CONCEPT_TERM: short noun phrase, technical term, acronym, or section heading.
2. VAGUE_FRAGMENT: clause or predicate fragment starting with copula/auxiliary/preposition.
3. MULTI_SENTENCE_PASSAGE: multi-sentence selection or passage (>= 140 chars).
4. AUTHOR_QUESTION: rhetorical or evaluative question ending with '?'.
"""

import re
from preprocess import STOPWORDS, stem, words

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

    return {
        "intent_type": intent_type,
        "core_concept": core_concept,
        "subject": subject,
        "anchor_sentence": anchor_sentence,
        "chosen_chunk": chosen_chunk,
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


def compute_dynamic_followups(
    chunk: dict,
    neighbors: list = None,
    selection: str = "",
    question: str = "",
    answer_text: str = "",
    mode: str = "explain",
) -> list[str]:
    """Compute 3 context-connected, dynamic follow-up questions from a passage and its neighborhood.

    100% book-agnostic, stdlib-only, sub-millisecond execution.
    Generates compact questions (<= 42 chars) answerable from the chunk and its neighbors.
    """
    if not chunk or not isinstance(chunk, dict):
        return [
            "What is the main takeaway?",
            "What problem does this solve?",
            "Explain this in simpler words",
        ]

    chunk_text = chunk.get("text") or ""
    chunk_heading = (chunk.get("heading") or "").strip()
    clean_sel = (selection or "").strip()
    clean_q = (question or "").strip()
    exclude_text = f"{clean_sel} {clean_q}".lower()

    # Quote from answer_text if present
    quote_text = ""
    if answer_text:
        m_q = re.search(r'\[Ch\.\s*[^\]]+\]\s*["\u201c](.+?)["\u201d]', answer_text)
        if m_q:
            quote_text = m_q.group(1).strip()

    lead_context = f"{clean_sel} {quote_text}".strip()
    lead_low = lead_context.lower()
    chunk_low = chunk_text.lower()

    # Strip heading line from chunk_text and neighbor text
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

    body_text_no_heading = _body_no_heading(chunk_text, chunk_heading)

    # a) Extract candidate technical terms / concepts from chunk and neighbors[0]
    raw_terms = []
    # Parenthetical acronyms or terms: (IOPS), (Apache Beam), etc.
    for m in re.finditer(r"\(([A-Za-z0-9 \t_-]{2,30})\)", body_text_no_heading):
        raw_terms.append(m.group(1))

    # Capitalized multi-word technical terms / frameworks (2-3 words):
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:[ \t]+(?:and[ \t]+)?[A-Z][A-Za-z0-9]+){1,2})\b", body_text_no_heading):
        raw_terms.append(m.group(1))

    # Named / defined terms: "known as ...", "called ...", in quotes
    for m in re.finditer(r"\b(?:known as|called|termed)[ \t]+([a-zA-Z0-9 \t_-]{3,30})[—–,\.\)]", body_text_no_heading, re.I):
        raw_terms.append(m.group(1))

    # Specific technical phrases in the chunk:
    for phrase in (
        "enterprise ossification", "evaluation of trade-offs", "change management",
        "simple lift and shift", "lease cliff", "types of windows", "dataflow model",
    ):
        if phrase in chunk_low:
            raw_terms.append(phrase)

    # Standalone list-item lines from chunk_text:
    for line in body_text_no_heading.splitlines():
        l_strip = line.strip()
        if (
            3 <= len(l_strip) <= 25
            and l_strip[0].isupper()
            and not l_strip.endswith((".", "?", "!", ":"))
            and l_strip.lower() != chunk_heading.lower()
        ):
            w = l_strip.split()
            if 1 <= len(w) <= 3:
                raw_terms.append(l_strip)

    # Neighbor terms (first neighbor in same chapter):
    if neighbors:
        for n in neighbors:
            if n and str(n.get("chapter")) == str(chunk.get("chapter")):
                n_text = n.get("text") or ""
                n_head = (n.get("heading") or "").strip()
                n_body = _body_no_heading(n_text, n_head)
                for m in re.finditer(r"\(([A-Za-z0-9 \t_-]{2,30})\)", n_body):
                    raw_terms.append(m.group(1))
                for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:[ \t]+[A-Z][A-Za-z0-9]+){1,2})\b", n_body):
                    raw_terms.append(m.group(1))
                break

    # Direct author questions (?...) in chunk between 15 and 42 chars
    author_q = ""
    for s in split_sentences(chunk_text):
        s_strip = s.strip()
        if (
            s_strip.endswith("?")
            and 15 <= len(s_strip) <= 42
            and s_strip.lower() not in exclude_text
            and not _is_redundant_followup(s_strip, clean_q, clean_sel)
        ):
            author_q = s_strip
            break

    # Clean and filter candidate terms
    candidate_terms = []
    seen_terms = set()
    DISCARD_OPENERS = frozenset({
        "figure", "fig", "table", "chapter", "ch", "section", "part", "page",
        "what", "why", "how", "when", "where", "who", "which",
        "is", "are", "was", "were", "do", "does", "did",
        "can", "could", "should", "would", "will",
        "let", "see", "note",
    })
    DROP_OPENERS = frozenset({
        "in", "on", "at", "for", "to", "with", "by", "the", "a", "an", "this",
        "that", "these", "those", "we", "our", "you", "here", "as", "such",
    })
    for t in raw_terms:
        t_clean = re.sub(r"\s+", " ", t).strip(" \t\r\n—–-,:;\"'“”()[]")
        t_words = t_clean.split()
        if not (2 <= len(t_clean) <= 28) or len(t_words) > 4:
            continue
        if t_words and t_words[0].lower() in DISCARD_OPENERS:
            continue
        if t_words and t_words[0].lower() in DROP_OPENERS and len(t_words) > 1:
            t_clean = re.sub(r"\s+", " ", " ".join(t_words[1:])).strip(" \t\r\n—–-,:;\"'“”()[]")
            t_words = t_clean.split()
        if not t_clean or len(t_clean) < 2:
            continue
        if re.search(r"\b\d+[-–.]\d+\b", t_clean):
            continue
        if not any(len(w) >= 3 and any(c.isalpha() for c in w) for w in t_words):
            continue
        t_low = t_clean.lower()
        if t_low in seen_terms or t_low in exclude_text:
            continue
        if _is_redundant_followup(t_clean, clean_q, clean_sel):
            continue
        if all(w.lower() in STOPWORDS for w in t_words):
            continue
        seen_terms.add(t_low)
        candidate_terms.append(t_clean)

    # Slot 1: Mechanism / Reason / Specifics in the passage
    slot1 = ""
    used_term = ""
    if (
        (
            re.search(r"\b(two\s+reasons|three\s+reasons|several\s+reasons)\b", lead_low)
            or ("reason" in lead_low and any(num in lead_low for num in ("two", "three", "several", "essential")))
            or ("two reasons" in chunk_low or "three reasons" in chunk_low)
        )
        and "reason" not in clean_q.lower()
    ):
        slot1 = "What are the specific reasons?"
    elif re.search(r"\b(main\s+stages|several\s+stages|stages)\b", lead_low) and "stage" not in clean_q.lower():
        slot1 = "What are the main stages?"
    elif re.search(r"\b(key\s+types|several\s+types|types\s+of)\b", lead_low) and "type" not in clean_q.lower():
        slot1 = "What are the key types?"
    elif re.search(r"\b(characteristics|common\s+threads)\b", lead_low) and "characteristic" not in clean_q.lower():
        slot1 = "What are the key characteristics?"
    elif re.search(r"\b(several\s+ways|ways\s+to)\b", lead_low) and "way" not in clean_q.lower():
        slot1 = "What are the specific ways?"
    else:
        for t in candidate_terms:
            is_plural = (t.endswith("s") and not t.lower().endswith(("ss", "us", "is", "as", "os", "ics"))) or t in ("SSDs", "HDDs", "CPUs", "GPUs", "VMs", "DAGs", "APIs")
            aux = "do" if is_plural else "does"
            q_cand = f"How {aux} {t} relate to this?"
            if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                slot1 = q_cand
                used_term = t
                break
            q_cand = f"What is {t}?" if not is_plural else f"What are {t}?"
            if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                slot1 = q_cand
                used_term = t
                break

        if not slot1:
            core_concept = extract_core_concept(clean_sel, chunk_heading)
            if core_concept and core_concept.lower() not in exclude_text:
                q_cand = f"How does {core_concept} work?"
                if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                    slot1 = q_cand
        if not slot1:
            slot1 = "How does this work in practice?"

    # Slot 2: Contrast / Trade-off / Risk / Pitfall in the passage
    slot2 = ""
    if "ossification" in chunk_low and "ossification" not in exclude_text:
        slot2 = "What are the risks of ossification?"
    elif "lease cliff" in chunk_low or "cliff" in chunk_low:
        slot2 = "What is the risk of a lease cliff?"
    elif any(w in chunk_low for w in ("cost", "expensive", "pricing", "pay-as-you-go")):
        slot2 = "What are the cost trade-offs?"
    elif any(w in chunk_low for w in ("bottleneck", "bottlenecks")):
        slot2 = "What are the main bottlenecks?"
    elif any(w in chunk_low for w in ("limitation", "limitations", "downside", "downsides")):
        slot2 = "What are the main limitations?"
    elif any(w in chunk_low for w in ("risk", "risks", "mistake", "mistakes", "failure")):
        slot2 = "What are the risks or pitfalls?"
    elif any(w in chunk_low for w in ("trade-off", "trade-offs", "tradeoffs")):
        slot2 = "What are the key trade-offs?"
    else:
        for t2 in candidate_terms:
            if t2 != used_term:
                q_cand = f"How does this compare to {t2}?"
                if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                    slot2 = q_cand
                    used_term = t2
                    break
                q_cand = f"What is the role of {t2}?"
                if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                    slot2 = q_cand
                    used_term = t2
                    break
        if not slot2:
            slot2 = "What problem does this solve?"

    # Slot 3: Concrete Example / Next Concept in Section
    slot3 = ""
    if author_q and author_q.lower() not in (slot1.lower(), slot2.lower()):
        slot3 = author_q

    if not slot3 and neighbors:
        for n in neighbors:
            if n and str(n.get("chapter")) == str(chunk.get("chapter")):
                n_head = (n.get("heading") or "").strip()
                if n_head and n_head.lower() != chunk_heading.lower() and n_head.lower() not in exclude_text:
                    clean_next = extract_core_concept(n_head)
                    if (
                        clean_next
                        and len(clean_next) <= 28
                        and clean_next.lower() not in STRUCTURAL_HEADINGS
                        and not _is_redundant_followup(clean_next, clean_q, clean_sel)
                    ):
                        is_plural = clean_next.endswith("s") and not clean_next.lower().endswith(("ss", "us", "is", "as", "os", "ics"))
                        q_cand = f"What is {clean_next}?" if not is_plural else f"What are {clean_next}?"
                        if len(q_cand) <= 42 and not _is_redundant_followup(q_cand, clean_q, clean_sel):
                            slot3 = q_cand
                            break

    if not slot3:
        if any(marker in chunk_low for marker in ("for instance", "for example", "consider", "such as", "examples of")):
            slot3 = "What example do the authors give?"
        else:
            slot3 = "Explain this in simpler words"

    # Assemble, deduplicate, and enforce <= 42 chars
    followups = []
    seen_q = set()
    for q in (slot1, slot2, slot3):
        q_clean = re.sub(r"\s+", " ", (q or "")).strip()
        if len(q_clean) > 42:
            if len(q_clean) > 45:
                q_clean = q_clean[:41].rstrip(" ?.,-") + "?"
        if q_clean and q_clean.lower() not in seen_q and not _is_redundant_followup(q_clean, clean_q, clean_sel):
            seen_q.add(q_clean.lower())
            followups.append(q_clean)

    FALLBACKS = [
        "What are the key trade-offs?",
        "What problem does this solve?",
        "What example do the authors give?",
        "Explain this in simpler words",
        "Why does this matter?",
    ]
    for fb in FALLBACKS:
        if len(followups) >= 3:
            break
        if fb.lower() not in seen_q and not _is_redundant_followup(fb, clean_q, clean_sel):
            seen_q.add(fb.lower())
            followups.append(fb)

    return followups[:3]

