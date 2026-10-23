import functools
import re

from engine.answering.canonical import STEM_WORDS, canonical_query
from engine.answering.comparison import _half_covered
from engine.answering.context import retrieval_context
from engine.answering.conversation import _resolve_contextual_query
from engine.answering.listshape import _without_heading
from engine.answering.messages import SIMPLIFY_RE, answer_user_message, user_message
from engine.answering.pipeline import begin_turn, finalize, simplify_shortcut
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
from engine.answering.shared import (
    FRAMING_WORDS,
    SPAN_MIN_CHARS,
    _SENTENCE_SPLIT_RE,
    _TRAP_QUERY_RE,
    _WHITESPACE_RE,
    _clean_boilerplate_gloss,
    _fold,
    _sentences,
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


PARAPHRASE_LIMIT = 5


TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]", re.I)


QUOTE_PATTERN = re.compile(r"[\"“]([^\"“”]+)[\"”]")


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
    folded = (question or "").lower()
    return any(cue in folded for cue in SIMPLE_CUES)


def _has_passage_evidence(asked_form, passages, word_map):
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
    try:
        completion = generate_fn(
            SYSTEM, user_message(question, passages, history=history), model,
            prefill="[Ch. ",
        )
    except Exception:
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
    t = begin_turn(index, question, generate_fn, history, pin_chunk, selection, heading, model, "answer")
    if t is None:
        return _refusal([])
    shortcut = simplify_shortcut(t)
    if shortcut is not None:
        return shortcut
    question, history, clean_history = t.question, t.history, t.clean_history
    generate_fn, effective_pin = t.generate_fn, t.effective_pin
    resolved_question = _resolve_contextual_query(
        index, question, pin_chunk=effective_pin, selection=selection,
        heading=heading, history=history,
    )
    asked_form = canonical_query(resolved_question) if canonical else resolved_question
    context = retrieval_context(
        index, asked_form, search_fn, generate_fn, pin_chunk=effective_pin,
        end_chunk_id=end_chunk_id, history=history, selection=selection,
        embed_fn=embed_fn,
    )
    passages = context["passages"]
    t.set_retrieval(resolved_question, asked_form, context)
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
    return finalize(t, body, simple_words(asked_form))


def _clean_rewrite(text):
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain_body(index, context, generate_fn, model):
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
    first = (text or "").strip().split("\n", 1)[0].strip()
    return first == REFUSAL or first.lower() == REFUSAL.lower()


def _strip_fake_quotes(text, passages):
    def keep(match):
        inner = match.group(1)
        if any(_quote_in_passage(inner, hit.get("text") or "") for hit in passages):
            return match.group(0)
        return inner
    return QUOTE_PATTERN.sub(keep, text)


@functools.lru_cache(maxsize=2048)
def _tokens(text):
    return frozenset(word for word in _punctuation_plain(text).split() if len(word) > 2)


def _claim_after_tag(rest):
    first_line = rest.split("\n", 1)[0]
    quoted = QUOTE_PATTERN.search(first_line)
    if quoted:
        return quoted.group(1).strip()
    return re.sub(r"\s+", " ", first_line).strip()


def _sentence_claims(text):
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
