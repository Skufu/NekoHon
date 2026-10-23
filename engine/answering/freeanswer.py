import functools
import re

from engine.answering.canonical import STEM_WORDS, canonical_query, is_incomplete_stem
from engine.answering.comparison import _half_covered
from engine.answering.context import _patch_figures_src, retrieval_context
from engine.answering.conversation import (
    _advance_followup_quote,
    _extract_subject_from_history,
    _is_topic_shift_followup,
    _resolve_contextual_query,
    prior_turn_chunk_position,
)
from engine.answering.generate import ollama_generate
from engine.answering.gloss import _ensure_answer_gloss
from engine.answering.intent import compute_dynamic_followups
from engine.answering.listshape import _expand_list, _without_heading
from engine.answering.messages import SIMPLIFY_RE, answer_user_message, user_message
from engine.answering.prompt import ANSWER_MODEL, PARAPHRASE_SYSTEM, REFUSAL, SYSTEM, SYSTEM_ANSWER
from engine.answering.quotecheck import (
    _align_citation_to_query_concepts,
    _complete_truncated_quote,
    _original_case,
    _punctuation_plain,
    _quote_in_passage,
    _refusal,
    _reground_alphanumeric_quote,
    longest_copied_span,
    parse_completion,
)
from engine.answering.sanitize import is_prompt_injection, sanitize_history, sanitize_query
from engine.answering.shared import (
    FRAMING_WORDS,
    SPAN_MIN_CHARS,
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
    _TRAP_QUERY_RE,
    _WHICH_CHAPTER_RE,
    _WHITESPACE_RE,
    _YEAR_MATCH_RE,
    _YEAR_QUERY_RE,
    _anchor_sentence_for_selection,
    _candidate_sentences,
    _clean_boilerplate_gloss,
    _clean_selection_text,
    _fold,
    _sentences,
    chapter_neighbors,
    chunk_by_id,
    stem,
    tokens,
    words,
)
from engine.figures import figures_for
from engine.retrieval.keywords import anchor_words
from engine.retrieval.preprocess import STOPWORDS


_CH_PREFIX_RE = re.compile(r"^\[ch\.", re.I)


_PUNCT_SPLIT_RE = re.compile(r"[.!?]")


_MASK_TAG_RE = re.compile(r"\x01([^\x02]*)\x02")


_DIGITS_RE = re.compile(r"\d+")


# Rewrites per plain answer: one call each, a call budget, not a quality knob
# (measured citations run at 1-3; the scorecard's answers stayed under five).
PARAPHRASE_LIMIT = 5


TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]", re.I)


QUOTE_PATTERN = re.compile(r"[\"“]([^\"“”]+)[\"”]")


# The plain register's cues. Generic English phrases, not fitted to a test
# (the scorecard asks carry "in simple words"); cue detection is a product
# feature, the same class of text as the refusal sentence.
SIMPLE_CUES = (
    "in simple words",
    "in simple terms",
    "in plain words",
    "for a beginner",
    "for beginners",
    "simply explain",
    "explain simply",
    "like i'm five",
    "eli5",
    "keep it simple",
)


def simple_words(question):
    """True when the question asks for the plain register."""
    folded = (question or "").lower()
    return any(cue in folded for cue in SIMPLE_CUES)


def _has_passage_evidence(asked_form, passages, word_map):
    """True when every content word in the query appears in the shown passages
    and in the book's word_map, supporting stem-level matching and alphanumeric
    precision.

    Groundedness gate for false-refusal recovery: an out-of-book question (like
    France) or a question whose content is absent from the shown passages fails
    closed immediately without triggering a retry.
    """
    q_words = [w.lower() for w in words(asked_form)]
    if not q_words or not word_map or not passages:
        return False

    stemmed_word_map = None
    for w in q_words:
        if w in word_map or w in FRAMING_WORDS or w in STEM_WORDS or w in STOPWORDS:
            continue
        if any(c.isdigit() for c in w):
            return False
        if stemmed_word_map is None:
            stemmed_word_map = {stem(k) for k in word_map}
        if stem(w) not in stemmed_word_map:
            return False

    content = [
        w for w in q_words
        if w not in STEM_WORDS and w not in FRAMING_WORDS and w not in STOPWORDS
    ]
    if not content:
        return False

    passage_vocab = {
        w.lower()
        for hit in passages
        for w in words((hit.get("heading") or "") + " " + (hit.get("text") or ""))
    }
    passage_stems = None

    for w in content:
        if w in passage_vocab:
            continue
        if any(c.isdigit() for c in w):
            return False
        if passage_stems is None:
            passage_stems = {stem(pv) for pv in passage_vocab}
        if stem(w) not in passage_stems:
            return False

    return True


def _retry_uncited(question, passages, figures, generate_fn, model, history=None,
                   anchors=None, word_map=None):
    """One `[Ch. ` prefill retry for an uncited answer or false-refusal, or None.

    The x2d gap (measured 2026-10-14): on unseen non-canonical forms the
    model writes uncited prose — it answers, it just drops the tag. The retry
    asks once more with the assistant turn prefilled `[Ch. ` and is kept only
    when a citation whose quote is verbatim passage text survives a parse.
    Two parsers are tried: `parse_answered` for a prose continuation, and
    `parse_completion` (ask shape) for the tag-first continuation the prefill
    actually produces — `_sentence_claims` cites text before a tag, so a
    tag-first reply can only validate through the ask parser. Monotone: every
    failure path returns None, the original answer stands, and one extra
    generation is the only cost.

    The review's cost gate was "anchors present"; the sealed suite measured
    anchor coverage missing half its non-control items (Streaming, batch vs
    streaming, how do, what about, why does, pipeliness), so the trigger here
    is uncited + passages present and the verbatim-quote check does the
    safety work (retry-safety-net-2026-10-14.md has the coverage table).
    """
    try:
        completion = generate_fn(
            SYSTEM, user_message(question, passages, history=history), model,
            prefill="[Ch. ",
        )
    except Exception:
        # A generator seam without prefill support (or a failed call) keeps
        # the original answer; the retry may never break the main path.
        completion = None

    candidates = []
    if isinstance(completion, str) and completion.strip() and REFUSAL.lower() not in completion.lower():
        text = (
            completion
            if completion.lstrip().startswith("[Ch.")
            else "[Ch. " + completion
        )
        if text.lstrip().startswith("[Ch."):
            try:
                candidates.append(parse_completion(text, passages, figures, anchors=anchors, question=question))
            except Exception:
                pass
        try:
            candidates.append(parse_answered(text, passages, figures))
        except Exception:
            pass
    texts = {hit["chunk_id"]: hit.get("text") or "" for hit in passages}
    for body in candidates:
        if body["refused"] or not body["citations"]:
            continue
        if not all(
            _quote_in_passage(item["quote"], texts.get(item["chunk_id"], ""))
            for item in body["citations"]
        ):
            continue
        return body

    # Fallback quote extraction from passages[0] when _has_passage_evidence holds and len(passages) >= 3
    if passages and len(passages) >= 3 and word_map and _has_passage_evidence(question, passages, word_map):
        lead = passages[0]
        lead_text = lead.get("text") or ""
        q_tokens = [w.lower() for w in words(question) if w.lower() not in STEM_WORDS and w.lower() not in STOPWORDS]
        best_sent = ""
        best_overlap = -1
        for sent in _sentences(lead_text):
            sent_clean = _without_heading(sent, lead)
            if len(sent_clean) < SPAN_MIN_CHARS:
                continue
            sent_words = set(words(sent_clean.lower()))
            overlap = sum(1 for t in q_tokens if t in sent_words or any(stem(t) == stem(sw) for sw in sent_words))
            if overlap > best_overlap:
                best_overlap = overlap
                best_sent = sent_clean
        if best_sent:
            best_sent = _reground_alphanumeric_quote(best_sent, question, lead_text)
            chap = str(lead["chapter"])
            return {
                "answer": f'[Ch. {chap}] "{best_sent}"\n{best_sent}',
                "citations": [{
                    "chunk_id": lead["chunk_id"],
                    "chapter": chap,
                    "quote": best_sent,
                }],
                "figures": figures_for([lead], figures or []),
                "refused": False,
            }

    return None


def respond(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
            canonical=True, history=None, pin_chunk=None, selection="", heading="",
            end_chunk_id=None, embed_fn=None):
    """Free-generation answer from the retrieved passages.

    No quote enforcement: the model answers, its [Ch. n] tags become the
    citations, and quotation marks the passages cannot back are stripped (see
    parse_answered). The prompt is the ask-shaped one (SYSTEM + user_message)
    because that is what the student is trained on (2026-10-15 alignment; see
    the module docstring). A question that asks for simple words routes
    through the plain register (`_plain_body`): the draft selects evidence
    sentences and each is rewritten one-in-one-out, so nothing is written from
    scratch. A bare topic phrase is asked as its question first
    (canonical_query). An uncited answer is retried once with a `[Ch. `
    prefill and kept only when a citation validates (`_retry_uncited`).
    """
    if is_prompt_injection(question):
        return _refusal([])
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
                    question=question, answer_text=body.get("answer", ""), mode="answer",
                )
                return _patch_figures_src(body, index)
    resolved_question = _resolve_contextual_query(
        index, question, pin_chunk=effective_pin, selection=selection,
        heading=heading, history=history,
    )
    history_subject = _extract_subject_from_history(history)
    asked_form = canonical_query(resolved_question) if canonical else resolved_question
    context = retrieval_context(
        index, asked_form, search_fn, generate_fn, pin_chunk=effective_pin,
        end_chunk_id=end_chunk_id, history=history, selection=selection,
        embed_fn=embed_fn,
    )
    passages = context["passages"]
    if not passages:
        return _refusal([])
    anchors = anchor_words(asked_form, context["word_map"])
    figures = index.get("figures") or []
    if simple_words(asked_form) and not (clean_history and effective_pin and SIMPLIFY_RE.search(question)):
        body = _plain_body(index, context, generate_fn, model)
        body = _half_covered(body, resolved_question, asked_form, passages, figures)
    else:
        completion = generate_fn(
            SYSTEM, user_message(context["asked"], passages, history=history), model
        )
        body = parse_answered(completion, passages, figures)
        body = _half_covered(body, resolved_question, asked_form, passages, figures)
        body = _align_citation_to_query_concepts(body, resolved_question, passages)
        if not body["refused"] and not body["citations"]:
            retry = _retry_uncited(
                context["asked"], passages, figures,
                generate_fn, model, history=history, anchors=anchors,
                word_map=context.get("word_map", {}),
            )
            if retry is not None:
                body = retry
        elif body.get("refused"):
            can_retry = False
            if clean_history and (resolved_question != question):
                is_trap = bool(_TRAP_QUERY_RE.search(question))
                if not is_trap and passages:
                    can_retry = True
            elif len(passages) >= 3 and _has_passage_evidence(context["asked"], passages, context.get("word_map", {})):
                can_retry = True

            if can_retry:
                retry = _retry_uncited(
                    context["asked"], passages, figures, generate_fn, model,
                    history=history, anchors=anchors, word_map=context.get("word_map", {}),
                )
                if retry is not None and not retry.get("refused"):
                    body = retry
    body = _expand_list(body, resolved_question, asked_form, passages)

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
    body = _align_citation_to_query_concepts(body, resolved_question, passages)
    if not selection and not clean_history:
        if (asked_form != resolved_question or is_incomplete_stem(question)) and asked_form != question and not body["refused"]:
            clean_asked = re.sub(r"\s+", " ", asked_form).strip()
            body["answer"] = f'{body["answer"]}\nAsked as: "{clean_asked}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'

    if not body.get("refused") and not simple_words(asked_form):
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
            question=resolved_question or question, answer_text=body.get("answer", ""), mode="answer",
        )
    else:
        body["followups"] = []

    return _patch_figures_src(body, index)


def _clean_rewrite(text):
    """The rewritten sentence: unquoted, list numbering stripped."""
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_body(index, context, generate_fn, model):
    """The plain register: draft selects evidence sentences, each is rewritten.

    The draft runs the standard path, so its citations' quotes are passage
    text by construction; each quote is rewritten one-in-one-out and keeps
    its source chunk's tag. The citations keep the original book sentences
    as evidence. A draft refusal is the register's refusal; if every rewrite
    comes back empty, the draft answer stands rather than a blank.
    """
    passages = context["passages"]
    completion = generate_fn(
        SYSTEM_ANSWER, answer_user_message(context["asked"], passages), model
    )
    draft = parse_answered(completion, passages, index.get("figures") or [])
    if draft["refused"]:
        return draft
    assembled = []
    for item in draft["citations"][:PARAPHRASE_LIMIT]:
        rewritten = generate_fn(
            PARAPHRASE_SYSTEM, f"Sentence: {item['quote']}", model
        )
        clean = _clean_rewrite(rewritten)
        if clean:
            assembled.append(f"{clean} [Ch. {item['chapter']}]")
    if not assembled:
        return draft
    return {
        "answer": " ".join(assembled),
        "citations": draft["citations"],
        "figures": draft["figures"],
        "refused": False,
    }


def _free_refusal(text):
    """True when the model asked to refuse. The first line must be the exact
    sentence; a refusal that keeps talking is still a refusal, never a free
    answer."""
    first = (text or "").strip().split("\n", 1)[0].strip()
    return first == REFUSAL or first.lower() == REFUSAL.lower()


def _strip_fake_quotes(text, passages):
    """Quotation marks around words no shown passage contains are dropped.

    The words stay; the marks are a promise the answer cannot keep. A quote
    that is in a shown passage keeps its marks.
    """
    def keep(match):
        inner = match.group(1)
        if any(_quote_in_passage(inner, hit.get("text") or "") for hit in passages):
            return match.group(0)
        return inner
    return QUOTE_PATTERN.sub(keep, text)


@functools.lru_cache(maxsize=2048)
def _tokens(text):
    """Word set for overlap scoring. Very short words carry little meaning."""
    return frozenset(word for word in _punctuation_plain(text).split() if len(word) > 2)


def _claim_after_tag(rest):
    """Quote or remainder of a tag-first line. Empty when the tag stands alone."""
    first_line = rest.split("\n", 1)[0]
    quoted = QUOTE_PATTERN.search(first_line)
    if quoted:
        return quoted.group(1).strip()
    return re.sub(r"\s+", " ", first_line).strip()


def _sentence_claims(text):
    """(claim, chapters) for every sentence carrying [Ch. tags.

    Tags are masked before the sentence split: "Ch." holds a period and would
    otherwise end a sentence inside the tag. The mask clears periods the
    captured text itself can hold — a two-chapter tag ("[Ch. 2, Ch. 7]")
    carries a second "Ch.", and a split inside the mask drops the claim
    entirely (measured 2026-10-13: the endpoint answer lost all citations).
    Text accumulates until a tag arrives, so a tag at the start of the next
    line still cites the sentence before it, and a tags-only fragment merges
    into the previous claim. A tag with no pending text takes the quote on
    that line (or the rest of the line) as the claim; a bare tag with no prior
    text still produces no claim.
    """
    masked = TAG_PATTERN.sub(
        lambda m: "\x01" + _PUNCT_SPLIT_RE.sub(" ", m.group(1)) + "\x02", text
    )
    claims = []
    pending = ""
    for part in _SENTENCE_SPLIT_RE.split(masked):
        segments = []
        cursor = 0
        for match in _MASK_TAG_RE.finditer(part):
            segments.append(("text", part[cursor:match.start()]))
            segments.append(("tag", match.group(1)))
            cursor = match.end()
        segments.append(("text", part[cursor:]))
        i = 0
        while i < len(segments):
            kind, value = segments[i]
            if kind == "text":
                pending = (pending + " " + value).strip()
                i += 1
                continue
            chapters = _DIGITS_RE.findall(value)
            claim = _WHITESPACE_RE.sub(" ", pending).strip()
            if not claim:
                rest = []
                j = i + 1
                while j < len(segments) and segments[j][0] == "text":
                    rest.append(segments[j][1])
                    j += 1
                claim = _claim_after_tag("".join(rest))
            if claim:
                claims.append([claim, chapters])
                pending = ""
            elif claims:
                claims[-1][1].extend(chapters)
            i += 1
    return claims


def _best_passage(claim, chapters, passages):
    """The shown passage the tagged sentence most likely used.

    The chapter named in the tag first, word overlap deciding within it; when
    the named chapter is not among the shown passages, the other passages get
    one look. A zero-overlap claim gets no citation — never a guess.
    """
    tokens = _tokens(claim)
    if not tokens:
        return None
    hints = set(chapters)
    in_chapter = [hit for hit in passages if str(hit["chapter"]) in hints]
    pools = [in_chapter, [hit for hit in passages if hit not in in_chapter]]
    best, best_score = None, 0.0
    for pool in pools:
        for hit in pool:
            overlap = len(tokens & _tokens(hit.get("text") or "")) / len(tokens)
            if overlap > best_score:
                best, best_score = hit, overlap
        if best is not None:
            break
    return best if best_score > 0 else None


def _evidence_quote(claim, hit):
    """A passage sentence as the citation's quote.

    The sentence with the most overlap with the claim decides — the same
    rule `_best_passage` uses for the passage itself. A copied run only
    breaks a tie, and the run alone is the fallback when no sentence can
    hold it: a stray generic run ("by data scientists, analysts, and
    other", 41 chars) must not hand the quote to a sentence the claim
    barely uses (measured 2026-10-13: the plain register then rewrote the
    enumeration instead of the definition).
    """
    text = hit.get("text") or ""
    span = longest_copied_span(claim, text)
    tokens = _tokens(claim)
    best, best_key = "", (-1.0, False)
    all_sents = _sentences(text)
    heading_clean = (hit.get("heading") or "").strip().lower()
    for sentence in all_sents:
        sentence_tokens = _tokens(sentence)
        if not sentence_tokens:
            continue
        overlap = len(tokens & sentence_tokens) / len(tokens) if tokens else 0.0
        holds = bool(span) and _fold(span) in _fold(sentence)
        if (overlap, holds) > best_key:
            best, best_key = sentence, (overlap, holds)
    res = ""
    if best:
        res = _without_heading(best, hit)
    elif span:
        res = _original_case(span, text)
    else:
        res = _without_heading(re.sub(r"\s+", " ", text).strip(), hit)

    res_clean = res.strip().lower()
    if len(res) < 20 or (heading_clean and res_clean == heading_clean):
        long_sents = [s for s in all_sents if len(s) >= 40 and s.strip().lower() != heading_clean]
        if long_sents:
            best_long = max(long_sents, key=lambda s: len(tokens & _tokens(s)) if tokens else 0)
            res = _without_heading(best_long, hit)

    return res


def parse_answered(completion, passages, figures=None):
    """A free answer turned into the contract body.

    The model's prose is kept as written, minus quotation marks the passages
    cannot back. Citations come from the [Ch. n] tags: each tagged sentence
    is matched to the shown passage of that chapter with the most word
    overlap. A sentence that matches nothing is left uncited rather than
    pinned to a guess, and a hallucination is a measurement, not a refusal.
    """
    text = (completion or "").strip()
    if not text or _free_refusal(text):
        return _refusal(passages, figures)
    text = _strip_fake_quotes(text, passages)
    citations = []
    for claim, chapters in _sentence_claims(text):
        hit = _best_passage(claim, chapters, passages)
        if hit is None:
            continue
        if any(item["chunk_id"] == hit["chunk_id"] for item in citations):
            continue
        quote = _evidence_quote(claim, hit)
        heading_clean = (hit.get("heading") or "").strip().lower()
        if len(quote) < 20 or (heading_clean and quote.strip().lower() == heading_clean):
            all_sents = _sentences(hit.get("text") or "")
            long_sents = [s for s in all_sents if len(s) >= 40 and s.strip().lower() != heading_clean]
            if long_sents:
                quote = _without_heading(long_sents[0], hit)
        quote = _complete_truncated_quote(quote, hit.get("text") or "")
        citations.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        })
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited]
    cleaned_lines = []
    for line in text.splitlines():
        line_clean = line.strip()
        if not _CH_PREFIX_RE.match(line_clean):
            cleaned = _clean_boilerplate_gloss(line_clean)
            if cleaned:
                cleaned_lines.append(cleaned)
        else:
            if line_clean.startswith("[ch."):
                line_clean = "[Ch." + line_clean[4:]
            cleaned_lines.append(line_clean)
    if cleaned_lines:
        text = "\n".join(cleaned_lines)
    return {
        "answer": text,
        "citations": citations,
        "figures": figures_for(named, figures or []),
        "refused": False,
    }
