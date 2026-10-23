import re
from dataclasses import dataclass, field

from engine.answering.canonical import STEM_WORDS, is_incomplete_stem
from engine.answering.context import _patch_figures_src
from engine.answering.conversation import (
    _advance_followup_quote,
    _extract_subject_from_history,
    _is_topic_shift_followup,
    prior_turn_chunk_position,
)
from engine.answering.generate import ollama_generate
from engine.answering.gloss import _ensure_answer_gloss
from engine.answering.intent import compute_dynamic_followups
from engine.answering.listshape import _expand_list
from engine.answering.messages import SIMPLIFY_RE
from engine.answering.quotecheck import (
    _align_citation_to_query_concepts,
    _complete_truncated_quote,
    _quote_in_passage,
    _refusal,
)
from engine.answering.sanitize import is_prompt_injection, sanitize_history, sanitize_query
from engine.answering.shared import (
    FRAMING_WORDS,
    _CHAPTER_DIGITS_RE,
    _CHAPTER_NUM_RE,
    _CODE_MATCH_RE,
    _CODE_QUERY_RE,
    _IN_GREATER_DETAIL_RE,
    _OVERHEAD_EXPANDED_RE,
    _OVERHEAD_RE,
    _PRICE_MATCH_RE,
    _PRICE_QUERY_RE,
    _SENTENCE_SPLIT_RE,
    _TAG_AND_QUOTE_RE,
    _WHICH_CHAPTER_RE,
    _YEAR_MATCH_RE,
    _YEAR_QUERY_RE,
    _anchor_sentence_for_selection,
    _candidate_sentences,
    _clean_selection_text,
    chapter_neighbors,
    chunk_by_id,
    stem,
    tokens,
    words,
)
from engine.figures import figures_for
from engine.retrieval.preprocess import STOPWORDS


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
    topic_shift = _is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    return Turn(index, question, history, clean_history, topic_shift, effective_pin,
                pin_chunk, selection, heading, model, generate_fn, is_live, mode)


def _unpack(t):
    return (t.index, t.question, t.history, t.clean_history, t.topic_shift, t.effective_pin,
            t.pin_chunk, t.selection, t.heading, t.model, t.generate_fn, t.is_live, t.mode)


def simplify_shortcut(t):
    (index, question, history, clean_history, topic_shift, effective_pin, pin_chunk,
     selection, heading, model, generate_fn, is_live, mode) = _unpack(t)
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
            m_q = _TAG_AND_QUOTE_RE.search(prior_a)
            prior_quote = m_q.group(2).strip() if m_q else ""
            chunk_text = target_chunk_obj.get("text") or ""
            chosen_quote = ""
            if prior_quote and (prior_quote in chunk_text or prior_quote.lower() in chunk_text.lower()):
                chosen_quote = _complete_truncated_quote(prior_quote, chunk_text)
            if not chosen_quote:
                cands = _candidate_sentences(chunk_text, target_chunk_obj.get("heading") or "")
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
                body = _ensure_answer_gloss(
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
                return _patch_figures_src(body, index)
    return None


def advance_followup(t, body):
    (index, question, history, clean_history, topic_shift, effective_pin, pin_chunk,
     selection, heading, model, generate_fn, is_live, mode) = _unpack(t)
    resolved_question, asked_form, passages, context = t.resolved_question, t.asked_form, t.passages, t.context
    figures = index.get("figures") or []
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
            adv_quote = _advance_followup_quote(target_chunk_obj, passages[1:3] if len(passages) > 1 else [], prior_quote, question)
            if adv_quote:
                first_cite = body["citations"][0] if (not body.get("refused") and body.get("citations")) else None
                cite_quote = first_cite.get("quote", "") if first_cite else ""
                if body.get("refused") or cite_quote == prior_quote:
                    adv_chunk = target_chunk_obj
                    if not _quote_in_passage(adv_quote, target_chunk_obj.get("text", "")):
                        for p in passages[1:3]:
                            if _quote_in_passage(adv_quote, p.get("text", "")):
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
    (index, question, history, clean_history, topic_shift, effective_pin, pin_chunk,
     selection, heading, model, generate_fn, is_live, mode) = _unpack(t)
    resolved_question, asked_form, passages, context = t.resolved_question, t.asked_form, t.passages, t.context
    figures = index.get("figures") or []
    if selection and pin_chunk:
        pin_chunk_obj = None
        if isinstance(pin_chunk, dict):
            pin_chunk_obj = pin_chunk
        elif isinstance(pin_chunk, str):
            pin_chunk_obj = chunk_by_id(index, pin_chunk)
        if pin_chunk_obj is not None:
            clean_sel = _clean_selection_text(selection)
            anchor_quote = _anchor_sentence_for_selection(pin_chunk_obj, clean_sel)
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
    return body


def history_guards(t, body):
    (index, question, history, clean_history, topic_shift, effective_pin, pin_chunk,
     selection, heading, model, generate_fn, is_live, mode) = _unpack(t)
    resolved_question, asked_form, passages, context = t.resolved_question, t.asked_form, t.passages, t.context
    figures = index.get("figures") or []
    history_subject = _extract_subject_from_history(history)
    if clean_history and (resolved_question != question) and not body.get("refused") and not topic_shift:
        if _WHICH_CHAPTER_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _CHAPTER_NUM_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _IN_GREATER_DETAIL_RE.search(sent) and _CHAPTER_NUM_RE.search(sent):
                            sent_clean = sent.strip().strip("\"'“”")
                            chap_m = _CHAPTER_DIGITS_RE.search(sent_clean)
                            chap_num = chap_m.group(1) if chap_m else str(p.get("chapter", ""))
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nChapter {chap_num} covers this in greater detail.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _CHAPTER_NUM_RE.search(body["citations"][0].get("quote", "")):
                        break

        if _OVERHEAD_RE.search(question):
            first_q = body["citations"][0].get("quote", "") if body.get("citations") else ""
            if not _OVERHEAD_EXPANDED_RE.search(first_q):
                for p in passages:
                    for sent in _SENTENCE_SPLIT_RE.split(p.get("text") or ""):
                        if _OVERHEAD_RE.search(sent) and len(sent) >= 30:
                            sent_clean = sent.strip().strip("\"'“”")
                            body["citations"] = [{
                                "chunk_id": p.get("chunk_id"),
                                "chapter": str(p.get("chapter")),
                                "quote": sent_clean,
                            }]
                            body["answer"] = f'[Ch. {p.get("chapter")}] "{sent_clean}"\nManaging this system requires substantial operational overhead and resources.'
                            body["refused"] = False
                            break
                    if body.get("citations") and _OVERHEAD_RE.search(body["citations"][0].get("quote", "")):
                        break

        if not body.get("citations"):
            body = _refusal(passages, figures)
        else:
            first_cite = body["citations"][0]
            first_chunk_id = first_cite.get("chunk_id")
            first_quote = first_cite.get("quote", "")
            cited_chunk = next((c for c in passages if c.get("chunk_id") == first_chunk_id), None)
            if not cited_chunk:
                body = _refusal(passages, figures)
            elif history_subject:
                subj_tokens = [
                    t.lower() for t in tokens(history_subject)
                    if len(t) > 2 and t.lower() not in STEM_WORDS and t.lower() not in FRAMING_WORDS and t.lower() not in STOPWORDS
                ]
                if subj_tokens:
                    c_text = (cited_chunk.get("heading") or "").lower() + " " + (cited_chunk.get("text") or "").lower()
                    c_stems = {stem(w) for w in words(c_text)}
                    has_subj = any(t in c_text or stem(t) in c_stems for t in subj_tokens)
                    last_ans = clean_history[-1].get("answer") or ""
                    last_chap_m = re.search(r"\[Ch\.\s*([^\]]+)\]", last_ans)
                    prior_chap = last_chap_m.group(1).strip().rstrip(".") if last_chap_m else None
                    if prior_chap and str(cited_chunk.get("chapter")) == prior_chap:
                        has_subj = True
                    if not has_subj:
                        body = _refusal(passages, figures)
            if not body.get("refused"):
                if _YEAR_QUERY_RE.search(question):
                    if not _YEAR_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _PRICE_QUERY_RE.search(question):
                    if not _PRICE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
                elif _CODE_QUERY_RE.search(question):
                    if not _CODE_MATCH_RE.search(first_quote):
                        body = _refusal(passages, figures)
    return body


def finish_answer(t, body, plain):
    (index, question, history, clean_history, topic_shift, effective_pin, pin_chunk,
     selection, heading, model, generate_fn, is_live, mode) = _unpack(t)
    resolved_question, asked_form, passages, context = t.resolved_question, t.asked_form, t.passages, t.context
    figures = index.get("figures") or []
    body = _align_citation_to_query_concepts(body, resolved_question, passages)
    if not selection and not clean_history:
        if (asked_form != resolved_question or is_incomplete_stem(question)) and asked_form != question and not body["refused"]:
            clean_asked = re.sub(r"\s+", " ", asked_form).strip()
            body["answer"] = f'{body["answer"]}\nAsked as: "{clean_asked}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'

    if not body.get("refused") and not plain:
        body = _ensure_answer_gloss(
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

    return _patch_figures_src(body, index)


def finalize(t, body, plain):
    body = _expand_list(body, t.resolved_question, t.asked_form, t.passages)
    advance_followup(t, body)
    pin_anchor_quote(t, body)
    body = history_guards(t, body)
    return finish_answer(t, body, plain)
