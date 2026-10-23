import re
from dataclasses import dataclass, field

from engine.answering.canonical import STEM_WORDS, is_incomplete_stem
from engine.answering.context import patch_figures_src
from engine.answering.conversation import (
    advance_followup_quote,
    extract_subject_from_history,
    is_topic_shift_followup,
    prior_turn_chunk_position,
)
from engine.answering.generate import ollama_generate
from engine.answering.gloss import ensure_answer_gloss
from engine.answering.intent import compute_dynamic_followups
from engine.answering.listshape import expand_list
from engine.answering.messages import SIMPLIFY_RE
from engine.answering.quotecheck import (
    align_citation_to_query_concepts,
    complete_truncated_quote,
    quote_in_passage,
    refusal_response,
)
from engine.answering.sanitize import is_prompt_injection, sanitize_history, sanitize_query
from engine.answering.indexmaps import chapter_neighbors, chunk_by_id
from engine.answering.selection import (
    anchor_sentence_for_selection,
    clean_selection_text,
    FRAMING_WORDS,
)
from engine.answering.sentences import (
    cached_tokens,
    cached_words,
    candidate_sentences,
    SENTENCE_SPLIT_RE,
)
from engine.answering.textrules import (
    CHAPTER_DIGITS_RE,
    CHAPTER_NUM_RE,
    CODE_MATCH_RE,
    CODE_QUERY_RE,
    IN_GREATER_DETAIL_RE,
    OVERHEAD_EXPANDED_RE,
    OVERHEAD_RE,
    PRICE_MATCH_RE,
    PRICE_QUERY_RE,
    TAG_AND_QUOTE_RE,
    WHICH_CHAPTER_RE,
    YEAR_MATCH_RE,
    YEAR_QUERY_RE,
)
from engine.retrieval.preprocess import stem, STOPWORDS
from engine.figures import figures_for


@dataclass
class Turn:
    index: dict
    question: str
    history: list
    clean_history: list
    topic_shift: bool
    effective_pin: object
    pin_chunk: object
    selection: str
    heading: str
    model: str
    generate_fn: object
    is_live: bool
    mode: str
    resolved_question: str = ""
    asked_form: str = ""
    context: dict = field(default_factory=dict)
    passages: list = field(default_factory=list)

    def set_retrieval(self, resolved_question, asked_form, context):
        self.resolved_question, self.asked_form, self.context = resolved_question, asked_form, context
        self.passages = context["passages"]


def begin_turn(index, question, generate_fn, history, pin_chunk, selection, heading, model, mode):
    if is_prompt_injection(question):
        return None
    question = sanitize_query(question)
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    history = sanitize_history(history)
    clean_history = [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]
    topic_shift = is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    return Turn(index, question, history, clean_history, topic_shift, effective_pin,
                pin_chunk, selection, heading, model, generate_fn, is_live, mode)


def simplify_shortcut(t):
    index = t.index
    question = t.question
    history = t.history
    clean_history = t.clean_history
    topic_shift = t.topic_shift
    effective_pin = t.effective_pin
    selection = t.selection
    heading = t.heading
    model = t.model
    generate_fn = t.generate_fn
    is_live = t.is_live
    mode = t.mode
    if clean_history and not topic_shift and SIMPLIFY_RE.search(question):
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = chunk_by_id(index, effective_pin)
        if target_chunk_obj is None and clean_history:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            prior_pos = prior_turn_chunk_position(index, prior_a)
            if prior_pos is not None:
                target_chunk_obj = index["chunks"][prior_pos]
        if target_chunk_obj is not None:
            prior_turn = clean_history[-1]
            prior_a = (prior_turn.get("answer") or "").strip()
            m_q = TAG_AND_QUOTE_RE.search(prior_a)
            prior_quote = m_q.group(2).strip() if m_q else ""
            chunk_text = target_chunk_obj.get("text") or ""
            chosen_quote = ""
            if prior_quote and (prior_quote in chunk_text or prior_quote.lower() in chunk_text.lower()):
                chosen_quote = complete_truncated_quote(prior_quote, chunk_text)
            if not chosen_quote:
                cands = candidate_sentences(chunk_text, target_chunk_obj.get("heading") or "")
                chosen_quote = cands[0] if cands else ""
            if chosen_quote:
                chap = str(target_chunk_obj.get("chapter", ""))
                body = {
                    "refused": False,
                    "citations": [{
                        "chunk_id": target_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": chosen_quote,
                    }],
                    "answer": f'[Ch. {chap}] "{chosen_quote}"',
                    "figures": figures_for([target_chunk_obj], index.get("figures") or []),
                }
                passages = [target_chunk_obj]
                body = ensure_answer_gloss(
                    index, body, question, passages, is_live=is_live,
                    history=history, selection=selection, heading=heading, model=model,
                    generate_fn=generate_fn,
                )
                lead_chunk = target_chunk_obj
                lead_neighbors = chapter_neighbors(index, chap, lead_chunk.get("chunk_id"))
                body["followups"] = compute_dynamic_followups(
                    lead_chunk, lead_neighbors, selection=selection,
                    question=question, answer_text=body.get("answer", ""), mode=mode,
                )
                return patch_figures_src(body, index)
    return None


def advance_followup(t, body):
    index = t.index
    question = t.question
    clean_history = t.clean_history
    topic_shift = t.topic_shift
    effective_pin = t.effective_pin
    passages = t.passages
    if clean_history and not SIMPLIFY_RE.search(question) and not topic_shift:
        prior_turn = clean_history[-1]
        prior_a = (prior_turn.get("answer") or "").strip()
        m_q = re.search(r"\[Ch\.\s*[^\]]+\]\s*[\"“](.+?)[\"”]", prior_a)
        prior_quote = m_q.group(1).strip() if m_q else ""
        target_chunk_obj = None
        if effective_pin:
            if isinstance(effective_pin, dict):
                target_chunk_obj = effective_pin
            elif isinstance(effective_pin, str):
                target_chunk_obj = chunk_by_id(index, effective_pin)
        if target_chunk_obj is None and passages:
            target_chunk_obj = passages[0]
        if target_chunk_obj is not None:
            adv_quote = advance_followup_quote(target_chunk_obj, passages[1:3] if len(passages) > 1 else [], prior_quote, question)
            if adv_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                if body.get("refused") or cite_quote == prior_quote:
                    adv_chunk = target_chunk_obj
                    if not quote_in_passage(adv_quote, target_chunk_obj.get("text", "")):
                        for p in passages[1:3]:
                            if quote_in_passage(adv_quote, p.get("text", "")):
                                adv_chunk = p
                                break
                    chap = str(adv_chunk.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": adv_chunk.get("chunk_id"),
                        "chapter": chap,
                        "quote": adv_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{adv_quote}"'
                    body["figures"] = figures_for([adv_chunk], index.get("figures") or [])


def pin_anchor_quote(t, body):
    index = t.index
    pin_chunk = t.pin_chunk
    selection = t.selection
    if selection and pin_chunk:
        pin_chunk_obj = None
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str):
            pin_chunk_obj = chunk_by_id(index, pin_chunk)
        if pin_chunk_obj is not None:
            clean_sel = clean_selection_text(selection)
            anchor_quote = anchor_sentence_for_selection(pin_chunk_obj, clean_sel)
            if anchor_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_id = first_cite.get("chunk_id") if first_cite else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                has_sel = clean_sel.lower() in cite_quote.lower()
                if body.get("refused") or cite_id != pin_chunk_obj.get("chunk_id") or not has_sel or len(cite_quote) > len(anchor_quote) + 30:
                    chap = str(pin_chunk_obj.get("chapter", ""))
                    body["refused"] = False
                    body["citations"] = [{
                        "chunk_id": pin_chunk_obj.get("chunk_id"),
                        "chapter": chap,
                        "quote": anchor_quote,
                    }]
                    body["answer"] = f'[Ch. {chap}] "{anchor_quote}"'
                    body["figures"] = figures_for([pin_chunk_obj], index.get("figures") or [])


def history_guards(t, body):
    index = t.index
    question = t.question
    history = t.history
    clean_history = t.clean_history
    topic_shift = t.topic_shift
    heading = t.heading
    resolved_question = t.resolved_question
    passages = t.passages
    figures = index.get("figures") or []
    history_subject = extract_subject_from_history(history)
    if clean_history and (resolved_question != question) and not body.get("refused") and not topic_shift:
        if WHICH_CHAPTER_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not CHAPTER_NUM_RE.search(first_q):
                for p in passages:
                    for sent in SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if IN_GREATER_DETAIL_RE.search(sent) and CHAPTER_NUM_RE.search(sent):
                            sent_clean = sent.strip().strip("\"'“”")
                            chap_m = CHAPTER_DIGITS_RE.search(sent_clean)
                            chap_num = chap_m.group(1) if chap_m else str(p.get("chapter", ""))
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nChapter {chap_num} covers this in greater detail.'
                            body["refused"] = False
                            break
                    if body.get("citations") and CHAPTER_NUM_RE.search(body["citations"][0].get("quote", "")):
                        break

        if OVERHEAD_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not OVERHEAD_EXPANDED_RE.search(first_q):
                for p in passages:
                    for sent in SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if OVERHEAD_RE.search(sent) and len(sent) >= 30:
                            sent_clean = sent.strip().strip("\"'“”")
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nManaging this system requires substantial operational overhead and resources.'
                            body["refused"] = False
                            break
                    if body.get("citations") and OVERHEAD_RE.search(body["citations"][0].get("quote", "")):
                        break

        if not body.get("citations"):
            body = refusal_response(passages, figures)
        else:
            first_cite = body["citations"][0]
            first_chunk_id = first_cite.get("chunk_id")
            first_quote = first_cite.get("quote", "")
            cited_chunk = next((c for c in passages if c.get("chunk_id") == first_chunk_id), None)
            if not cited_chunk:
                body = refusal_response(passages, figures)
            elif history_subject:
                subj_tokens = [
                    tok.lower() for tok in cached_tokens(history_subject)
                    if len(tok) > 2 and tok.lower() not in STEM_WORDS and tok.lower() not in FRAMING_WORDS and tok.lower() not in STOPWORDS
                ]
                if subj_tokens:
                    c_text = (cited_chunk.get("heading") or "").lower() + " " + (cited_chunk.get("text") or "").lower()
                    c_stems = {stem(w) for w in cached_words(c_text)}
                    has_subj = any(tok in c_text or stem(tok) in c_stems for tok in subj_tokens)
                    last_ans = clean_history[-1].get("answer") or ""
                    last_chap_m = re.search(r"\[Ch\.\s*([^\]]+)\]", last_ans)
                    prior_chap = last_chap_m.group(1).strip().rstrip(".") if last_chap_m else None
                    if prior_chap and str(cited_chunk.get("chapter")) == prior_chap:
                        has_subj = True
                    if not has_subj:
                        body = refusal_response(passages, figures)
            if not body.get("refused"):
                if YEAR_QUERY_RE.search(question):
                    if not YEAR_MATCH_RE.search(first_quote):
                        body = refusal_response(passages, figures)
                elif PRICE_QUERY_RE.search(question):
                    if not PRICE_MATCH_RE.search(first_quote):
                        body = refusal_response(passages, figures)
                elif CODE_QUERY_RE.search(question):
                    if not CODE_MATCH_RE.search(first_quote):
                        body = refusal_response(passages, figures)
    return body


def finish_answer(t, body, plain):
    index = t.index
    question = t.question
    history = t.history
    clean_history = t.clean_history
    selection = t.selection
    heading = t.heading
    model = t.model
    generate_fn = t.generate_fn
    is_live = t.is_live
    mode = t.mode
    resolved_question = t.resolved_question
    asked_form = t.asked_form
    passages = t.passages
    context = t.context
    body = align_citation_to_query_concepts(body, resolved_question, passages)
    if not selection and not clean_history:
        if (asked_form != resolved_question or is_incomplete_stem(question)) and asked_form != question and not body["refused"]:
            clean_asked = re.sub(r"\s+", " ", asked_form).strip()
            body["answer"] = f'{body["answer"]}\nAsked as: "{clean_asked}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'

    if not body.get("refused") and not plain:
        body = ensure_answer_gloss(
            index, body, resolved_question, passages, is_live=is_live,
            history=history, selection=selection, heading=heading, model=model,
            generate_fn=generate_fn,
        )
        first_cite_id = body["citations"][0].get("chunk_id") if body.get("citations") else None
        lead_chunk = next((c for c in passages if c.get("chunk_id") == first_cite_id), passages[0]) if passages else {}
        lead_neighbors = [p for p in passages if p != lead_chunk and str(p.get("chapter")) == str(lead_chunk.get("chapter"))]
        body["followups"] = compute_dynamic_followups(
            lead_chunk, lead_neighbors, selection=selection,
            question=resolved_question or question, answer_text=body.get("answer", ""), mode=mode,
        )
    else:
        body["followups"] = []

    return patch_figures_src(body, index)


def finalize(t, body, plain):
    body = expand_list(body, t.resolved_question, t.asked_form, t.passages)
    advance_followup(t, body)
    pin_anchor_quote(t, body)
    body = history_guards(t, body)
    return finish_answer(t, body, plain)
