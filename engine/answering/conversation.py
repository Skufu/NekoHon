import re

from engine.answering.canonical import is_deictic_question, is_incomplete_stem
from engine.answering.intent import META_TRANSITION_RE
from engine.answering.listshape import list_ask
from engine.answering.messages import SIMPLIFY_RE
from engine.answering.quotecheck import complete_truncated_quote, quote_in_passage
from engine.answering.indexmaps import chunk_by_id
from engine.answering.selection import clean_selection_text, extract_query_entities, FRAMING_WORDS
from engine.answering.sentences import cached_words, candidate_sentences
from engine.answering.textrules import (
    ATTRIBUTION_MARKERS,
    AUTHOR_NAME_RE,
    PARAGRAPH_CAP,
    TAG_AND_QUOTE_RE,
    TOPIC_SHIFT_CONCEPT_RE,
)
from engine.retrieval.preprocess import STOPWORDS


def prior_turn_chunk_position(index, prior_answer):
    m = TAG_AND_QUOTE_RE.search(prior_answer)
    if not m:
        return None
    prior_chap = m.group(1).strip().rstrip(".")
    snippet = m.group(2).strip()[:50].lower()
    chunks = index.get("chunks") or []
    for i, c in enumerate(chunks):
        if str(c.get("chapter")) == prior_chap and snippet in (c.get("text") or "").lower():
            return i
    for i, c in enumerate(chunks):
        if snippet in (c.get("text") or "").lower():
            return i
    return None


_WORD_ALPHA_RE = re.compile(r"\b[a-zA-Z]+\b")


_REASONS_QUERY_RE = re.compile(r"\b(specific\s+reasons|reasons|reason|why|main\s+stages|stages|key\s+types|types|characteristics|ways)\b")


_EXAMPLES_QUERY_RE = re.compile(r"\b(example|examples|instance|illustrate)\b")


_RISKS_QUERY_RE = re.compile(r"\b(risk|risks|pitfall|pitfalls|bottleneck|bottlenecks|cost|costs|expensive|trade-off|trade-offs|limitation|limitations|downside|downsides|ossification|cliff|mistake|failure)\b")


_ATTRIBUTION_QUERY_RE = re.compile(r"\b(who\s+created|who\s+introduced|who\s+coined|who\s+founded|who\s+proposed|who\s+invented|creator|inventor|author|authored)\b")


_EXTRACT_SUBJ_CAND_RE = re.compile(r"^\s*(?:A|An|The)?\s*([A-Za-z0-9\s_-]{3,40}?)\s+(?:is|are|was|were|provides|serves|enables|means|refers|consists|helps|acts|describes)\b")


_EXTRACT_SUBJ_WHEN_RE = re.compile(r"\b(?:when|while)\s+(.+)", re.I)


_EXTRACT_SUBJ_STRIP_ACTION_RE = re.compile(r"^(selecting|evaluating|choosing|designing|building)\s+", re.I)


_EXTRACT_SUBJ_STRIP_ART_RE = re.compile(r"^(a|an|the)\s+", re.I)


_EXTRACT_SUBJ_WH_START_RE = re.compile(r"^(what|how|why|where|which|should|tell me about|explain)\s+(?:is|are|was|were|does|do|did|can|could|should)?\s*(?:\b(?:a|an|the|teams|engineers|users|we)\b)?\s*", re.I)


_EXTRACT_SUBJ_VERB_SPLIT_RE = re.compile(r"\s+(?:sit|sits|used|use|stand for|look|differ|consider|covered)\b", re.I)


_WH_STARTS = ("what", "which", "who", "whom", "whose", "where", "when", "why", "how")


_AUX_WORDS = ("is", "are", "was", "were", "do", "does", "did", "can", "could", "should", "would", "will")


_OPENER_WORDS = ("explain", "describe", "define", "compare", "tell", "show")


_SUB_PRONOUNS = frozenset({"it", "its", "that", "this", "these", "those"})


_CAND_PRONOUNS = frozenset({"it", "its", "this", "that"})


_RISK_KEYWORDS = ("ossification", "cliff", "bottleneck", "bottlenecks", "cost", "costs", "expensive", "risk", "risks", "pitfall", "pitfalls", "trade-off", "trade-offs", "limitation", "limitations", "downside", "downsides")


GENERIC_FOLLOWUP_RE = re.compile(
    r"^\s*(?:why\s+does\s+this\s+matter|explain\s+(?:in\s+)?simpler\s+words|simpler\s+words|"
    r"break\s+this\s+down|what\s+are\s+(?:the|its)\s+trade-?offs|what\s+are\s+trade-?offs|"
    r"trade-?offs|why\s+matter|tell\s+me\s+more|elaborate|simplify|how\s+does\s+this\s+work|"
    r"what\s+are\s+(?:the\s+)?specific\s+reasons|what\s+(?:are\s+the\s+)?reasons|"
    r"what\s+example\s+(?:do\s+the\s+authors\s+give|is\s+given)|"
    r"what\s+problem\s+does\s+this\s+solve|"
    r"what\s+are\s+the\s+risks(?:\s+or\s+pitfalls)?|"
    r"what\s+are\s+the\s+(?:main\s+stages|key\s+types|key\s+characteristics|specific\s+ways)|"
    r"what\s+are\s+the\s+(?:cost\s+trade-?offs|main\s+bottlenecks|main\s+limitations)|"
    r"how\s+does\s+.+?\s+relate\s+to\s+this|"
    r"how\s+does\s+this\s+compare\s+to\s+.+?|"
    r"what\s+is\s+the\s+role\s+of\s+.+?|"
    r"what\s+are\s+the\s+risks\s+of\s+.+?|"
    r"explain\s+(?:it\s+|this\s+|that\s+)?(?:more\s+)?simpl[ey](?:\s+words)?|"
    r"more\s+simply|simpler\s+words|in\s+simple\s+words|in\s+simpler\s+words|"
    r"simplify|simplification|make\s+(?:this|it)\s+simpler|put\s+(?:this|it)\s+simply|"
    r"in\s+plain\s+(?:english|words|terms)|plain\s+english|"
    r"break\s+(?:this|it|that)\s+down|"
    r"what\s+does\s+(?:this|that|it)\s+mean|"
    r"eli5|easier\s+to\s+understand|"
    r"shorter|in\s+one\s+(?:short\s+)?sentence|one\s+short\s+sentence|"
    r"main\s+takeaway|key\s+takeaway|summar(?:ize|y)(?:\s+(?:this|it))?|tl;dr"
    r")\s*\??\s*$",
    re.IGNORECASE,
)


def _is_generic_followup(q: str) -> bool:
    if not q:
        return True
    return bool(is_deictic_question(q) or GENERIC_FOLLOWUP_RE.match(q.strip()) or SIMPLIFY_RE.search(q.strip()))


def _extract_subject_from_query(s):
    if not s:
        return ""
    m_when = _EXTRACT_SUBJ_WHEN_RE.search(s)
    if m_when and len(m_when.group(1).split()) >= 2:
        cand = m_when.group(1).rstrip("?.!").strip()
        cand = _EXTRACT_SUBJ_STRIP_ACTION_RE.sub("", cand)
        cand = _EXTRACT_SUBJ_STRIP_ART_RE.sub("", cand)
        return cand
    q = s.strip().rstrip("?.!")
    m = _EXTRACT_SUBJ_WH_START_RE.match(q)
    if m:
        q = q[m.end():].strip()
    q = _EXTRACT_SUBJ_VERB_SPLIT_RE.split(q)[0].strip()
    return q or s


def extract_subject_from_history(history):
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if not clean_history:
        return ""

    for prev in reversed(clean_history):
        prev_q = (prev.get("question") or "").strip()
        if prev_q and not _is_generic_followup(prev_q):
            q_words = prev_q.split()
            first_w = q_words[0].lower() if q_words else ""
            if (len(q_words) <= 10 and not any(first_w.startswith(w) for w in _WH_STARTS)
                    and first_w not in _AUX_WORDS and first_w not in _OPENER_WORDS):
                return prev_q.strip(" ?.!\"'")
            sub = _extract_subject_from_query(prev_q)
            sub_tokens = set(_WORD_ALPHA_RE.findall(sub.lower()))
            if not (sub_tokens & _SUB_PRONOUNS):
                return sub

    for prev in reversed(clean_history):
        prev_a = (prev.get("answer") or "").strip()
        if prev_a:
            m_q = TAG_AND_QUOTE_RE.search(prev_a)
            if m_q:
                quote = m_q.group(1).strip()
                m_sub = _EXTRACT_SUBJ_CAND_RE.match(quote)
                if m_sub:
                    cand = m_sub.group(1).strip()
                    cand_tokens = set(_WORD_ALPHA_RE.findall(cand.lower()))
                    if not (cand_tokens & _CAND_PRONOUNS):
                        return cand

    return _extract_subject_from_query(clean_history[0].get("question") or "")


DEICTIC_REF_RE = re.compile(
    r"\b(it|its|this|that|these|those|they|them|their|there|such|same|former|latter|above|previous|prior)\b",
    re.IGNORECASE,
)


GENERIC_FACETS_RE = re.compile(
    r"\b(reason|reasons|stage|stages|type|types|trade-off|trade-offs|tradeoff|tradeoffs|"
    r"downside|downsides|limitation|limitations|risk|risks|pitfall|pitfalls|"
    r"bottleneck|bottlenecks|cost|costs|example|examples|chapter|created|invented|"
    r"coined|warn|handle|overhead|"
    r"drawback|drawbacks|disadvantage|disadvantages|advantage|advantages|benefit|benefits|"
    r"challenge|challenges|problem|problems|solve|solves|prevent|prevents|role|use\s+case|use\s+cases|"
    r"takeaway|takeaways|principle|principles|simply|simpler|shorter|plain\s+english|summary|summarize|analogy|eli5)\b",
    re.IGNORECASE,
)


CONVERSATIONAL_DIRECTIVES = frozenset({
    "simply", "simpler", "simple", "simplify", "shorter", "plain", "english", "summary",
    "summarize", "takeaway", "eli5", "analogy", "example", "examples", "drawback",
    "drawbacks", "trade-off", "trade-offs", "downside", "downsides", "benefit",
    "benefits", "advantage", "advantages", "disadvantage", "disadvantages",
    "problem", "problems", "solve", "solves", "stage", "stages", "step", "steps",
    "principle", "principles", "type", "types", "role", "overlap", "field", "fields",
    "manual", "process", "replace", "antipattern", "viewed", "matter", "mean",
    "work", "works", "fast", "faster", "slow", "cost", "costs", "why", "how",
    "who", "where", "when", "which", "difference", "compare", "relate", "stand",
    "for", "main", "key", "specific", "author", "authors", "give", "tell",
    "explain", "describe",
})


def _has_deictic_reference(question: str) -> bool:
    return bool(DEICTIC_REF_RE.search(question or ""))


def is_topic_shift_followup(question: str, history: list, selection: str = "", pin_chunk=None, index=None) -> bool:
    if not history:
        return False
    if (
        SIMPLIFY_RE.search(question)
        or is_deictic_question(question)
        or is_incomplete_stem(question)
        or _is_generic_followup(question)
        or _has_deictic_reference(question)
        or bool(GENERIC_FACETS_RE.search(question))
    ):
        return False

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    if not clean_history:
        return False

    q_novel = [
        w.lower() for w in cached_words(question)
        if w.lower() not in STOPWORDS and w.lower() not in FRAMING_WORDS and w.lower() not in CONVERSATIONAL_DIRECTIVES and len(w) >= 3
    ]
    if not q_novel:
        return False

    hist_words = set(cached_words((extract_subject_from_history(clean_history) or "").lower()))
    if selection:
        hist_words.update(w.lower() for w in cached_words(selection))
    last_turn = clean_history[-1]
    last_q = (last_turn.get("question") or "").strip()
    if last_q:
        hist_words.update(w.lower() for w in cached_words(last_q))
    last_a = (last_turn.get("answer") or "").strip()
    if last_a:
        hist_words.update(w.lower() for w in cached_words(last_a))

    pin_chunk_obj = None
    if pin_chunk:
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str) and index:
            pin_chunk_obj = chunk_by_id(index, pin_chunk)

    m_concept = TOPIC_SHIFT_CONCEPT_RE.match(question.strip())
    if m_concept:
        concept_target = m_concept.group(1).strip()
        target_words = {w.lower() for w in cached_words(concept_target) if w.lower() not in STOPWORDS and len(w) >= 2}
        if last_a and len(target_words) >= 3 and all(w in last_a.lower() for w in target_words):
            return False
        sub_words = {w.lower() for w in cached_words((extract_subject_from_history(clean_history) or "").lower()) if w.lower() not in STOPWORDS}
        if pin_chunk_obj is not None:
            p_head = (pin_chunk_obj.get("heading") or "").lower()
            if concept_target.lower() in p_head or (target_words and target_words.issubset({w.lower() for w in cached_words(p_head)})):
                return False
            if index:
                chunks = index.get("chunks") or []
                diff_heading = any(
                    c.get("chunk_id") != pin_chunk_obj.get("chunk_id")
                    and concept_target.lower() in (c.get("heading") or "").lower()
                    for c in chunks
                )
                if diff_heading:
                    return True
            p_text = (pin_chunk_obj.get("text") or "").lower()
            if len(target_words) >= 2 and all(w in p_text for w in target_words):
                return False
            if not all(w in p_text for w in target_words) and not target_words.issubset(sub_words):
                return True
            if not (target_words & sub_words):
                return True
            return False
        else:
            if not target_words.issubset(sub_words):
                return True
            if not (target_words & sub_words):
                return True
            return False
    else:
        if set(q_novel) & hist_words:
            return False
        if pin_chunk_obj is not None:
            pin_words = {w.lower() for w in cached_words(pin_chunk_obj.get("text", ""))}
            if set(q_novel) & pin_words:
                return False
        if len(q_novel) >= 2 and not (set(q_novel) & hist_words):
            if pin_chunk_obj is None or not (set(q_novel) & {w.lower() for w in cached_words(pin_chunk_obj.get("text", ""))}):
                return True
        return False


def rank_seq_chunks(seq_chunks, question, history_subject=None):
    q_lower = (question or "").lower()
    q_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", q_lower))

    def score_chunk(c):
        text = (c.get("heading") or "").lower() + " " + (c.get("text") or "").lower()
        score = 0
        if history_subject and history_subject.lower() in text:
            score += 25
        elif history_subject and any(w in text for w in history_subject.lower().split() if len(w) > 3):
            score += 15
        if re.search(r"\b(which\s+chapter|where\s+in\s+the\s+book)\b", q_lower):
            if "in greater detail" in text:
                score += 25
            if re.search(r"\bchapter\s+\d+\b", text):
                score += 20
        if re.search(r"\b(who\s+created|who\s+introduced|who\s+coined|who\s+founded|who\s+proposed|who\s+invented|creator|inventor)\b", q_lower):
            for marker in ("introduced", "created", "coined", "founded", "proposed", "author", "invented", "noted", "article", "book"):
                if marker in text:
                    score += 10
            orig_text = (c.get("text") or "")
            if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", orig_text):
                score += 10
        content_words = {w for w in q_words if len(w) > 3 and w not in STOPWORDS and w not in FRAMING_WORDS}
        for cw in content_words:
            if cw in text:
                score += 2
        if re.search(r"\b(reason|reasons|why|stages|types|ways|characteristics)\b", q_lower):
            for term in ("reason", "reasons", "first,", "second,", "third,", "because", "due to", "stages", "types"):
                if term in text:
                    score += 15
        if re.search(r"\b(example|examples|instance)\b", q_lower):
            for term in ("for example", "for instance", "such as", "consider", "example", "examples"):
                if term in text:
                    score += 15
        if re.search(r"\b(downside|downsides|disadvantage|disadvantages|drawback|drawbacks|con|cons|trade-off|trade-offs|tradeoff|tradeoffs|challenge|challenges|risk|risks)\b", q_lower):
            for term in ("disadvantage", "disadvantages", "downside", "downsides", "drawback", "drawbacks", "complexity", "bottleneck", "bottlenecks", "overhead", "costs", "trade-off", "trade-offs"):
                if term in text:
                    score += 15
        for term in ("overhead", "trade-offs", "tradeoffs", "latency", "throughput", "partition"):
            if term in text:
                score += 5
        return score

    return sorted(seq_chunks, key=score_chunk, reverse=True)


_HISTORY_DEICTIC_WORDS = {"it", "its", "this", "that", "these", "those", "they", "them", "such"}


def _resolve_from_history(q, subject):
    q_lower = q.lower()
    q_words = set(re.findall(r"\b[a-zA-Z]+\b", q_lower))
    deictic = q_words & _HISTORY_DEICTIC_WORDS
    if re.search(r"\b(its\s+downsides|its\s+disadvantages|its\s+pros\s+and\s+cons|its\s+drawbacks)\b", q_lower):
        return re.sub(r"\bits\b", f"the {subject}'s", q, flags=re.IGNORECASE)
    if re.search(r"\b(warn\s+against\s+that|warn\s+about\s+that|caution\s+against\s+that)\b", q_lower):
        return re.sub(r"\bthat\b", f"{subject}", q, flags=re.IGNORECASE)
    if re.search(r"\b(handle\s+late\s+data|handles\s+late\s+data)\b", q_lower) and "it" in q_words:
        return re.sub(r"\bit\b", f"{subject}", q, flags=re.IGNORECASE)
    if re.search(r"\b(that\s+stage|that\s+phase|that\s+step)\b", q_lower):
        return re.sub(r"\bthat\s+stage\b", f"the {subject} stage", q, flags=re.IGNORECASE)
    if re.search(r"\b(this\s+architectural\s+pattern|this\s+pattern|this\s+architecture)\b", q_lower):
        return re.sub(r"\bthis\s+(architectural\s+pattern|pattern|architecture)\b", f"{subject}", q, flags=re.IGNORECASE)
    if re.search(r"\busing\s+it\b", q_lower):
        return re.sub(r"\busing\s+it\b", f"using {subject}", q, flags=re.IGNORECASE)
    if re.search(r"\bfor\s+(this|that)\b", q_lower):
        return re.sub(r"\bfor\s+(this|that)\b", f"for {subject}", q, flags=re.IGNORECASE)
    if re.search(r"\bopen-source\s+it\b", q_lower):
        return re.sub(r"\bopen-source\s+it\b", f"open-source {subject}", q, flags=re.IGNORECASE)
    if deictic:
        if re.search(r"\b(how\s+does|how\s+is|what\s+is|what\s+are|why\s+does|why\s+is)\s+it\b", q_lower):
            return re.sub(r"\bit\b", f"{subject}", q, count=1, flags=re.IGNORECASE)
        if re.search(r"\b(what\s+are|what\s+is)\s+its\b", q_lower):
            return re.sub(r"\bits\b", f"{subject}'s", q, count=1, flags=re.IGNORECASE)
        return f"Regarding {subject}: {q}"
    if subject.lower() not in q_lower and (
        _is_generic_followup(q) or
        is_incomplete_stem(q) or
        bool(re.search(r"\b(type|tier|stage|phase|step)\s*\d+\b", q_lower)) or
        bool(GENERIC_FACETS_RE.search(q_lower))
    ):
        return f"Regarding {subject}: {q}"
    return None


def _resolve_from_selection(q, sel, head):
    if sel.lower() in q.lower():
        return None
    if is_deictic_question(q):
        if q.lower().startswith(("why", "how")):
            return f"{q.rstrip('?').strip()} ('{sel}')?"
        return f"What does '{sel}' mean in this passage?"
    if is_incomplete_stem(q):
        return f"{q.rstrip('?').strip()} {sel}?"
    if head:
        return f"In {head}, regarding '{sel}': {q}"
    return f"Regarding '{sel}': {q}"


def _stem_sentence(chunks, stem):
    for chunk in chunks:
        for sent in candidate_sentences(chunk.get("text") or "", chunk.get("heading") or ""):
            if sent.lower().startswith(stem + " ") and len(sent) >= 20:
                return sent
    return None


def _pin_search_pool(index, pin_chunk_obj):
    chunks = index.get("chunks") or []
    pool = [pin_chunk_obj]
    try:
        idx = chunks.index(pin_chunk_obj)
    except ValueError:
        return pool
    if idx > 0 and chunks[idx - 1].get("chapter") == pin_chunk_obj.get("chapter"):
        pool.append(chunks[idx - 1])
    if idx + 1 < len(chunks) and chunks[idx + 1].get("chapter") == pin_chunk_obj.get("chapter"):
        pool.append(chunks[idx + 1])
    return pool


def _resolve_incomplete_stem(index, q, head, pin_chunk_obj):
    stem = re.sub(r"[?!.,]", "", q.lower()).strip()
    if pin_chunk_obj is not None:
        sent = _stem_sentence(_pin_search_pool(index, pin_chunk_obj), stem)
        if sent:
            return sent
        h = head or pin_chunk_obj.get("heading", "")
        if h:
            return f"{q.rstrip('?')} {h}?"
    sent = _stem_sentence(index.get("chunks") or [], stem)
    if sent:
        return sent
    first_chunk = (index.get("chunks") or [{}])[0]
    first_head = first_chunk.get("heading") or head
    if first_head:
        return f"{q.rstrip('?')} {first_head}?"
    return None


def resolve_contextual_query(index, question, pin_chunk=None, selection="",
                              heading="", history=None):
    q = re.sub(r"\s+", " ", (question or "")).strip()
    sel = clean_selection_text(selection)
    head = re.sub(r"\s+", " ", (heading or "")).strip()

    pin_chunk_obj = None
    if pin_chunk and isinstance(pin_chunk, dict):
        pin_chunk_obj = pin_chunk
    elif pin_chunk and isinstance(pin_chunk, str):
        pin_chunk_obj = chunk_by_id(index, pin_chunk)

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]

    if clean_history:
        subject = extract_subject_from_history(clean_history) or sel
        if subject:
            resolved = _resolve_from_history(q, subject)
            if resolved is not None:
                return resolved

    if sel and not clean_history and len(sel.split()) <= 45:
        resolved = _resolve_from_selection(q, sel, head)
        if resolved is not None:
            return resolved

    if is_incomplete_stem(q):
        resolved = _resolve_incomplete_stem(index, q, head, pin_chunk_obj)
        if resolved is not None:
            return resolved

    return question


def _followup_pool(chunk_obj, neighbors):
    pool = [chunk_obj]
    for n in neighbors or []:
        if n and n != chunk_obj and n not in pool:
            pool.append(n)
    return pool


def _followup_sentence_score(s_clean, norm_s, norm_prior, c_text, q_low, q_tokens, query_entities, followup_question):
    s_low = s_clean.lower()
    score = 0

    if _REASONS_QUERY_RE.search(q_low):
        if s_low.startswith(("first,", "first ", "1.", "one reason")):
            score += 35
        elif s_low.startswith(("second,", "second ", "2.", "third,", "third ", "another reason")):
            score += 25
        elif any(w in s_low for w in ("first,", "second,", "third,", "because", "due to")):
            score += 20
        if norm_prior and norm_prior in c_text.lower():
            m_pos = c_text.lower().find(norm_prior)
            s_pos = c_text.lower().find(norm_s)
            if m_pos != -1 and s_pos > m_pos and s_pos - (m_pos + len(norm_prior)) < 400:
                score += 15

    if _EXAMPLES_QUERY_RE.search(q_low):
        if s_low.startswith(("for instance", "for example", "consider", "such as")):
            score += 35
        elif any(m in s_low for m in ("for instance", "for example", "such as")):
            score += 25
        elif "example" in s_low or "examples" in s_low:
            score += 15

    if _RISKS_QUERY_RE.search(q_low):
        for kw in _RISK_KEYWORDS:
            if kw in q_low and kw in s_low:
                score += 30
            elif kw in s_low:
                score += 10

    if _ATTRIBUTION_QUERY_RE.search(q_low):
        for marker in ATTRIBUTION_MARKERS:
            if marker in s_low:
                score += 15
        if AUTHOR_NAME_RE.search(s_clean):
            score += 20

    for t in q_tokens:
        if t in s_low:
            score += 5

    for ent in query_entities or ():
        if ent.lower() in s_low:
            score += 30 * len(ent.split())

    if list_ask(followup_question, followup_question) and ":" in s_clean and "," in s_clean:
        score += 25
    return score


def _expand_short_quote(sents, i, s_clean, c_text):
    s_low = s_clean.lower()
    is_short_or_continuation = (
        s_low.startswith(("first,", "second,", "for example", "for instance", "advertising platforms are another"))
        or len(s_clean) < 100
    )
    if not is_short_or_continuation:
        return s_clean
    if i + 1 < len(sents):
        next_s = sents[i + 1].strip()
        if len(next_s) >= 20 and not next_s.lower().startswith(("second,", "third,", "finally,")):
            combined = f"{s_clean} {next_s}"
            if len(combined) <= PARAGRAPH_CAP and quote_in_passage(combined, c_text):
                return combined
    elif i > 0:
        prev_s = sents[i - 1].strip()
        if len(prev_s) >= 20:
            combined = f"{prev_s} {s_clean}"
            if len(combined) <= PARAGRAPH_CAP and quote_in_passage(combined, c_text):
                return combined
    return s_clean


def advance_followup_quote(chunk_obj, neighbors=None, prior_quote="", followup_question=""):
    if not chunk_obj or not followup_question:
        return None

    if SIMPLIFY_RE.search(followup_question):
        return None

    q_low = followup_question.lower()
    q_tokens = [
        w.lower() for w in cached_words(q_low)
        if w.lower() not in STOPWORDS and w.lower() not in FRAMING_WORDS and len(w) >= 3
    ]
    query_entities = extract_query_entities(followup_question, chunk_obj.get("heading", ""))
    norm_prior = re.sub(r"[\s\"'“”]+", " ", prior_quote or "").strip().lower()

    scored_cands = []
    for c in _followup_pool(chunk_obj, neighbors):
        c_text = c.get("text") or ""
        sents = candidate_sentences(c_text, c.get("heading") or "")
        for i, s in enumerate(sents):
            s_clean = s.strip()
            if len(s_clean) < 30:
                continue
            norm_s = re.sub(r"[\s\"'“”]+", " ", s_clean).strip().lower()
            if norm_prior and (norm_s == norm_prior or norm_s in norm_prior or (len(norm_prior) >= 40 and norm_prior in norm_s)):
                continue
            if META_TRANSITION_RE.search(s_clean):
                continue
            score = _followup_sentence_score(
                s_clean, norm_s, norm_prior, c_text, q_low, q_tokens, query_entities, followup_question,
            )
            if c == chunk_obj:
                score += 2
            if score > 0:
                scored_cands.append((score, -i, _expand_short_quote(sents, i, s_clean, c_text), c))

    if not scored_cands:
        return None

    scored_cands.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_cand = scored_cands[0]
    if best_cand[0] >= 10:
        return complete_truncated_quote(best_cand[2], best_cand[3].get("text") or "")

    return None
