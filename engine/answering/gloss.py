import re

from engine.answering.conversation import (
    GENERIC_FACETS_RE,
    _advance_followup_quote,
    _is_topic_shift_followup,
)
from engine.answering.generate import ollama_generate
from engine.answering.intent import (
    INTENT_CONCEPT_TERM,
    INTENT_MULTI_SENTENCE,
    INTENT_VAGUE_FRAGMENT,
    META_TRANSITION_RE,
    analyze_intent,
    extract_core_concept,
    extract_enclosing_subject,
    split_sentences,
)
from engine.answering.listshape import _list_ask, _synthesize_list_answer
from engine.answering.messages import (
    SIMPLIFY_RE,
    _answer_gloss_user_message,
    _explain_gloss_user_message,
    _followup_gloss_user_message,
    user_message,
)
from engine.answering.prompt import (
    ANSWER_GLOSS_SYSTEM,
    ANSWER_MODEL,
    EXPLAIN_GLOSS_SYSTEM,
    FOLLOWUP_GLOSS_SYSTEM,
    REFUSAL,
    SYSTEM,
)
from engine.answering.quotecheck import _quote_in_passage
from engine.answering.shared import (
    _SENTENCE_SPLIT_RE,
    _candidate_sentences,
    _clean_boilerplate_gloss,
    _clean_selection_text,
    _extract_query_entities,
    chunk_by_id,
    chunk_position,
    fix_acronym_casing,
    words,
)
from engine.retrieval.preprocess import STOPWORDS


_GIBBERISH_DIGITS_RE = re.compile(r"\b(?:sentence|line|paragraph|passage)\s+\d+\b", re.I)


_GIBBERISH_NOUN_DIGITS_RE = re.compile(r"\b[A-Za-z]+\s+\d+\s+(?:negative|positive|again|reads?)\b", re.I)


_ADJACENT_REPEATED_WORD_RE = re.compile(r"\b([A-Za-z]{3,})\s+\1\b", re.I)


_SENTENCE_DANGLING_END_RE = re.compile(r"\b(?:the|a|an|also|again|to|of|in|for|with|and|or|that)\s*[.?!]$", re.I)


_META_COMMENTARY_RE = re.compile(r"\b(?:this|the)\s+(?:section|chapter|passage|book|authors?)\s+(?:introduces?|prepares?\s+readers|discusses?|mentions?|is\s+a\s+detour)\b", re.I)


_POINTER_META_LOCATION_RE = re.compile(r"\b(?:are|is)\s+(?:listed|discussed|covered|described|explained|found|shown|outlined|detailed|introduced)\s+in\s+(?:the|this|chapter|section|figure|part)\b|\b(?:in\s+the\s+introduction|see\s+chapter|see\s+section|see\s+figure|refer\s+to\s+chapter)\b", re.I)


_PROMPT_LEAKAGE_RE = re.compile(r"\b(?:do\s+not|don't|never)\s+(?:say|use|repeat|mention|start\s+with|include|write|output)\b", re.I)


def _has_content_word_overlap(s1: str, s2: str, exclude: str = "") -> bool:
    if not s1 or not s2:
        return False
    ex_words = {w.lower() for w in words(exclude)} if exclude else set()
    w1 = {w.lower() for w in words(s1) if len(w) >= 3 and w.lower() not in STOPWORDS and w.lower() not in ex_words}
    w2 = {w.lower() for w in words(s2) if len(w) >= 3 and w.lower() not in STOPWORDS and w.lower() not in ex_words}
    return bool(w1 & w2)


def _is_coherent_gloss(gloss: str, quote: str = "", question: str = "") -> bool:
    if not gloss or not isinstance(gloss, str):
        return False
    text = gloss.strip()
    if len(text) < 25:
        return False
    if _GIBBERISH_DIGITS_RE.search(text):
        return False
    if _GIBBERISH_NOUN_DIGITS_RE.search(text):
        return False
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    for s in sentences:
        s_words = [w.lower() for w in words(s) if len(w) >= 4 and w.lower() not in STOPWORDS]
        counts = {}
        for w in s_words:
            counts[w] = counts.get(w, 0) + 1
            if counts[w] >= 4:
                return False
    all_words = text.split()
    for i in range(len(all_words)):
        win = all_words[i:i + 25]
        win_content = [w.lower() for w in words(" ".join(win)) if len(w) >= 4 and w.lower() not in STOPWORDS]
        counts = {}
        for w in win_content:
            counts[w] = counts.get(w, 0) + 1
            if counts[w] >= 4:
                return False
    if _ADJACENT_REPEATED_WORD_RE.search(text):
        return False
    if _SENTENCE_DANGLING_END_RE.search(text):
        return False
    if _META_COMMENTARY_RE.search(text):
        return False
    if _POINTER_META_LOCATION_RE.search(text):
        return False
    if not text.lower().startswith("the passages do not mention") and _PROMPT_LEAKAGE_RE.search(text):
        return False
    if question and _list_ask(question, question):
        if "," not in text and " and " not in text.lower() and ";" not in text:
            return False
        if quote and quote.count(",") >= 2:
            q_words = {w.lower() for w in words(quote) if len(w) >= 3 and w.lower() not in STOPWORDS}
            t_words = {w.lower() for w in words(text) if len(w) >= 3 and w.lower() not in STOPWORDS}
            if len(q_words & t_words) < 2:
                return False
    if quote:
        norm_t = re.sub(r"[\s\"'“”]+", " ", text).strip().lower()
        norm_q = re.sub(r"[\s\"'“”]+", " ", quote).strip().lower()
        if norm_t == norm_q:
            return False
    return True


def _gloss_repeats_quote(gloss: str, quote: str) -> bool:
    g = re.sub(r"[\s\"'“”]+", " ", gloss or "").strip().lower()
    q = re.sub(r"[\s\"'“”]+", " ", quote or "").strip().lower()
    if not g or not q:
        return True
    if g == q or g.startswith(q) or q.startswith(g):
        return True
    g_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", g))
    q_words = set(re.findall(r"\b[a-zA-Z0-9]+\b", q))
    return len(g_words - q_words) < 3


def _synthesize_grounded_gloss(selection, quote, pin_chunk_obj, neighbors, generate_fn, model):
    heading = (pin_chunk_obj.get("heading") or "") if pin_chunk_obj else ""
    intent_info = analyze_intent(selection, heading, pin_chunk_obj, neighbors)
    intent_type = intent_info.get("intent_type") or INTENT_CONCEPT_TERM
    core_concept = intent_info.get("core_concept") or extract_core_concept(selection, heading)
    subject = intent_info.get("subject") or (extract_enclosing_subject(quote, selection) if quote else "")

    if intent_type == INTENT_CONCEPT_TERM:
        if intent_info.get("is_passing_mention"):
            q_synth = f"How does {core_concept} relate to {heading or 'this topic'} based strictly on this passage?"
        else:
            q_synth = f"What is {core_concept}?"
    elif intent_type == INTENT_VAGUE_FRAGMENT:
        q_synth = f"Why is {subject} described as {selection}?" if subject else f"What does {selection} mean?"
    elif intent_type == INTENT_MULTI_SENTENCE:
        q_synth = "What is the core takeaway of this passage?"
    else:
        q_synth = selection.strip()

    context_passages = [pin_chunk_obj] if pin_chunk_obj else []
    if neighbors:
        for n in neighbors:
            if n and n not in context_passages:
                context_passages.append(n)

    if generate_fn and context_passages:
        try:
            cand_reply = generate_fn(SYSTEM, user_message(q_synth, context_passages), model)
            if cand_reply and cand_reply != REFUSAL:
                lines = [ln.strip() for ln in cand_reply.splitlines() if ln.strip()]
                for ln in lines:
                    if re.match(r"^\[ch\.", ln, re.I) or ln.startswith('"') or ln.startswith("“") or ln.startswith("”"):
                        continue
                    cleaned_cand = _clean_boilerplate_gloss(ln, selection)
                    if _is_coherent_gloss(cleaned_cand, quote) and (
                        not intent_info.get("is_passing_mention")
                        or _has_content_word_overlap(cleaned_cand, quote, exclude=f"{selection} {heading}")
                    ):
                        return fix_acronym_casing(cleaned_cand)
        except Exception:
            pass

    if intent_type == INTENT_VAGUE_FRAGMENT:
        if subject:
            m = re.search(re.escape(selection.strip()), quote, re.IGNORECASE) if quote else None
            after_text = ""
            if m:
                after_text = quote[m.end():].strip().rstrip(".?!")
            if after_text:
                return fix_acronym_casing(f"The highlighted phrase refers to {subject}, explaining that it is {selection.lstrip()} {after_text}.")
            return fix_acronym_casing(f"The highlighted phrase refers to {subject} as {selection} in this section.")
        return fix_acronym_casing(f"The highlighted phrase characterizes the approach described in this sentence: {quote[:100]}.")

    if intent_type == INTENT_CONCEPT_TERM:
        if intent_info.get("is_passing_mention"):
            q_clean = quote.strip().rstrip(".?!") if quote else ""
            if q_clean:
                lead = (q_clean[0].lower() + q_clean[1:]) if (len(q_clean) > 1 and not q_clean[1].isupper()) else q_clean
                return fix_acronym_casing(f"In {heading or 'this section'}, {core_concept} connects to this topic—{lead}.")
            return fix_acronym_casing(f"{core_concept} relates to {heading or 'this topic'} as described in this section.")
        substantive = []
        for cand_c in context_passages:
            if not cand_c:
                continue
            cands = split_sentences(cand_c.get("text", ""))
            for s in cands:
                if len(s) >= 40 and not META_TRANSITION_RE.search(s):
                    if core_concept.lower() in s.lower() or any(w.lower() in s.lower() for w in words(core_concept) if w.lower() not in STOPWORDS):
                        substantive.append(s)
        if substantive:
            first_sub = substantive[0]
            if first_sub.lower().startswith("to understand"):
                return fix_acronym_casing(first_sub)
            if len(substantive) >= 2 and substantive[0] != substantive[1]:
                return fix_acronym_casing(f"{substantive[0]} {substantive[1]}")
            return fix_acronym_casing(substantive[0])
        return fix_acronym_casing(f"{core_concept} refers to the technical and operational model described in this section.")

    if intent_type == INTENT_MULTI_SENTENCE:
        sents = split_sentences(selection)
        non_examples = [s for s in sents if len(s) >= 40 and not s.lower().startswith(("for instance", "for example", "consider", "look at"))]
        if non_examples:
            cand = non_examples[0]
            if len(non_examples) > 1 and len(cand) + len(non_examples[-1]) < 250:
                cand = f"{cand} {non_examples[-1]}"
            cand_lead = (cand[0].lower() + cand[1:]) if len(cand) > 1 and not cand[1].isupper() else cand
            return fix_acronym_casing(f"This passage explains that {cand_lead}")
        return fix_acronym_casing("This passage analyzes the trade-offs and operational constraints between storage, capacity, and resource limits.")

    if quote:
        return fix_acronym_casing(f"The authors explain {selection} in this section: {quote[:120]}.")
    return fix_acronym_casing(f"The authors discuss {selection} in this section.")


def _strip_ch_tags(gloss):
    if re.match(r"^\[ch\.", gloss, re.I) and "\n" in gloss:
        gloss = gloss.split("\n", 1)[1].strip()
    return re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", gloss, flags=re.I).strip().strip("\"'“”")


def _live_gloss(generate_fn, system, prompt, model, context):
    try:
        raw = generate_fn(system, prompt, model)
    except Exception:
        raw = ""
    return _strip_ch_tags(_clean_boilerplate_gloss(raw, context))


def _is_good_gloss(gloss, quote, question):
    return bool(gloss) and _is_coherent_gloss(gloss, quote, question=question)


def _passage_sentence_gloss(chunk_obj, quote, question):
    for s in _candidate_sentences(chunk_obj.get("text") or "", chunk_obj.get("heading") or ""):
        if s != quote and len(s) >= 40 and not META_TRANSITION_RE.search(s) and _is_coherent_gloss(s, quote, question=question):
            return s
    return None


def _list_synth_gloss(question, quote, chunk_obj):
    if _list_ask(question, question):
        list_synth = _synthesize_list_answer(question, quote, chunk_obj)
        if list_synth and _is_coherent_gloss(list_synth, quote, question=question):
            return list_synth
    return None


def _list_or_sentence_fallback(new_gloss, question, quote, chunk_obj):
    if not _is_good_gloss(new_gloss, quote, question):
        list_synth = _list_synth_gloss(question, quote, chunk_obj)
        if list_synth:
            new_gloss = list_synth
    if not _is_good_gloss(new_gloss, quote, question):
        cand = _passage_sentence_gloss(chunk_obj, quote, question)
        if cand:
            new_gloss = cand
    return new_gloss


def _cited_neighbors(index, cite_id):
    chunks = index.get("chunks") or []
    neighbors = []
    i = chunk_position(index, cite_id)
    if i is not None:
        c = chunks[i]
        if i > 0 and chunks[i - 1].get("chapter") == c.get("chapter"):
            neighbors.append(chunks[i - 1])
        if i + 1 < len(chunks) and chunks[i + 1].get("chapter") == c.get("chapter"):
            neighbors.append(chunks[i + 1])
    return neighbors


def _norm_quote(text):
    return re.sub(r"[\s\"'“”]+", " ", text or "").strip().lower()


def _advance_cited_quote(first_cite, quote, first_line, chunk_obj, neighbors, prior_quote, question):
    adv_quote = _advance_followup_quote(chunk_obj, neighbors, prior_quote, question)
    if not adv_quote or adv_quote == quote:
        return quote, first_line
    adv_chunk = chunk_obj
    if not _quote_in_passage(adv_quote, chunk_obj.get("text", "")):
        for n in (neighbors or []):
            if n and _quote_in_passage(adv_quote, n.get("text", "")):
                adv_chunk = n
                break
    first_cite["quote"] = adv_quote
    first_cite["chunk_id"] = adv_chunk.get("chunk_id")
    first_cite["chapter"] = str(adv_chunk.get("chapter", first_cite.get("chapter", "")))
    return adv_quote, f'[Ch. {first_cite["chapter"]}] "{adv_quote}"'


def _entity_connection_gloss(target_entities, quote, heading, chunk_obj):
    sents = split_sentences(quote)
    matching_s = next((s for s in sents if any(ent.lower() in s.lower() for ent in target_entities)), quote)
    matching_s = re.sub(r"^(?:for example|for instance|in addition|specifically),?\s*", "", matching_s, flags=re.I).strip()
    ent_name = target_entities[0]
    sec_heading = heading or chunk_obj.get("heading", "")
    if sec_heading:
        return fix_acronym_casing(f"In {sec_heading}, {ent_name} connects to this topic: {matching_s}")
    return fix_acronym_casing(f"{ent_name} connects to this topic: {matching_s}")


def _followup_turn_gloss(clean_history, question, first_cite, quote, first_line, gloss_line, chunk_obj, neighbors,
                         target_entities, gloss_missing_query_entity, heading, is_live, generate_fn, model):
    prior_a = (clean_history[-1].get("answer") or "").strip()
    m_q = re.search(r"\[Ch\.\s*[^\]]+\]\s*[\"“](.+?)[\"”]", prior_a)
    prior_quote = m_q.group(1).strip() if m_q else ""
    norm_prior = _norm_quote(prior_quote)
    norm_curr = _norm_quote(quote)
    quote_repeated = bool(
        norm_prior and norm_curr and (
            norm_curr == norm_prior
            or norm_curr in norm_prior
            or (len(norm_prior) >= 40 and norm_prior in norm_curr)
        )
    )
    list_quote_missing_items = bool(_list_ask(question, question) and "," not in quote and ":" not in quote)
    simplify = bool(SIMPLIFY_RE.search(question))
    if (quote_repeated or list_quote_missing_items) and not simplify:
        quote, first_line = _advance_cited_quote(first_cite, quote, first_line, chunk_obj, neighbors, prior_quote, question)

    need_followup_gloss = (
        simplify
        or quote_repeated
        or list_quote_missing_items
        or (gloss_missing_query_entity and not GENERIC_FACETS_RE.search(question))
        or not gloss_line
        or _gloss_repeats_quote(gloss_line, quote)
        or not _is_coherent_gloss(gloss_line, quote, question=question)
    )
    if not need_followup_gloss:
        return gloss_line, quote, first_line

    new_gloss = ""
    if is_live:
        prompt = _followup_gloss_user_message(clean_history, question, quote, chunk_obj, neighbors)
        new_gloss = _live_gloss(generate_fn, FOLLOWUP_GLOSS_SYSTEM, prompt, model, question)
    new_gloss = _list_or_sentence_fallback(new_gloss, question, quote, chunk_obj)
    if target_entities and not GENERIC_FACETS_RE.search(question) and any(ent.lower() in quote.lower() for ent in target_entities) and not any(ent.lower() in (new_gloss or "").lower() for ent in target_entities):
        new_gloss = _entity_connection_gloss(target_entities, quote, heading, chunk_obj)
    return new_gloss, quote, first_line


def _selection_gloss(selection, quote, chunk_obj, neighbors, is_live, generate_fn, model):
    clean_sel = _clean_selection_text(selection)
    new_gloss = ""
    if is_live:
        prompt = _explain_gloss_user_message(clean_sel, quote, chunk_obj, neighbors)
        new_gloss = _live_gloss(generate_fn, EXPLAIN_GLOSS_SYSTEM, prompt, model, clean_sel)
    if not _is_good_gloss(new_gloss, quote, clean_sel):
        new_gloss = _synthesize_grounded_gloss(clean_sel, quote, chunk_obj, neighbors, generate_fn, model)
        if new_gloss:
            new_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", new_gloss, flags=re.I).strip().strip("\"'“”")
    if not _is_good_gloss(new_gloss, quote, clean_sel):
        cand = _passage_sentence_gloss(chunk_obj, quote, clean_sel)
        if cand:
            new_gloss = cand
    return new_gloss


def _plain_answer_gloss(question, quote, chunk_obj, is_live, generate_fn, model):
    new_gloss = ""
    if is_live:
        prompt = _answer_gloss_user_message(question, quote, chunk_obj)
        new_gloss = _live_gloss(generate_fn, ANSWER_GLOSS_SYSTEM, prompt, model, question)
    return _list_or_sentence_fallback(new_gloss, question, quote, chunk_obj)


def _ensure_answer_gloss(index, body, question, passages, is_live=False,
                         history=None, selection="", heading="", model=ANSWER_MODEL,
                         generate_fn=None):
    if not body or body.get("refused") or not body.get("citations") or not passages:
        return body

    generate_fn = generate_fn or ollama_generate

    first_cite = body["citations"][0]
    quote = first_cite.get("quote") or ""
    if not quote or "The passages do not mention" in (body.get("answer") or ""):
        return body

    ans = (body.get("answer") or "").strip()
    lines = [ln.strip() for ln in ans.splitlines() if ln.strip()]
    first_line = lines[0] if lines else f'[Ch. {first_cite.get("chapter", "")}] "{quote}"'
    gloss_line = lines[1] if len(lines) >= 2 else ""

    if gloss_line.startswith(("Asked as:", "Read as:")):
        gloss_line = ""

    cite_id = first_cite.get("chunk_id")
    chunk_obj = chunk_by_id(index, cite_id)
    if chunk_obj is None:
        chunk_obj = passages[0]
    neighbors = _cited_neighbors(index, cite_id)

    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]

    target_entities = _extract_query_entities(question, heading or chunk_obj.get("heading", "")) if clean_history else []
    gloss_missing_query_entity = bool(target_entities and gloss_line and not any(ent.lower() in gloss_line.lower() for ent in target_entities))

    new_gloss = ""
    topic_shift = _is_topic_shift_followup(question, history, selection)

    if clean_history and not topic_shift:
        new_gloss, quote, first_line = _followup_turn_gloss(
            clean_history, question, first_cite, quote, first_line, gloss_line, chunk_obj, neighbors,
            target_entities, gloss_missing_query_entity, heading, is_live, generate_fn, model,
        )
    elif selection:
        new_gloss = _selection_gloss(selection, quote, chunk_obj, neighbors, is_live, generate_fn, model)
    elif not gloss_line or _gloss_repeats_quote(gloss_line, quote) or not _is_coherent_gloss(gloss_line, quote, question=question):
        new_gloss = _plain_answer_gloss(question, quote, chunk_obj, is_live, generate_fn, model)

    if new_gloss and new_gloss != REFUSAL:
        extra_lines = [ln for ln in lines[1:] if ln.startswith(("Asked as:", "Read as:"))]
        res_lines = [first_line, new_gloss] + extra_lines
        body = dict(body)
        body["answer"] = "\n".join(res_lines)

    return body
