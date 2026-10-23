import difflib
import functools
import re

from engine.answering.canonical import STEM_WORDS
from engine.answering.prompt import REFUSAL
from engine.figures import figures_for
from engine.retrieval.preprocess import STOPWORDS
from engine.answering.shared import (
    FIGURE_REFERENCE,
    MIN_QUOTE_CHARS,
    MISS_QUOTE_CHARS,
    PARAGRAPH_CAP,
    SPAN_MIN_CHARS,
    _ATTRIBUTION_MARKERS,
    _AUTHOR_NAME_RE,
    _IOPS_RE,
    _NON_WORD_OR_UNDERSCORE_RE,
    _S3_RE,
    _SLA_SLO_RE,
    _TYPE_2_RE,
    _WHO_CREATED_RE,
    _candidate_sentences,
    _clean_boilerplate_gloss,
    _fold,
    _sentences,
    stem,
    tokens,
    words,
)
from engine.answering.listshape import _paragraph_around, _whole_paragraph, _without_heading
from engine.answering.comparison import _comparison_sides, _side_tokens


def _strip_quotes(text):
    text = text.strip()
    text = text.strip("\"'`“”")
    return re.sub(r"\s+", " ", text).strip(" .")


def _short_sentence(raw, quote):
    """True when a sub-SPAN_MIN_CHARS quote is a complete sentence.

    Shape, not length: an upper-case start and terminal punctuation in the
    text the model wrote, plus real cleaned length. "Everything fails, all the
    time." passes (measured 2026-10-13); a mid-sentence fragment or a bare
    heading ("Hot, warm, and cold data") does not.
    """
    raw = (raw or "").strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return False
    return raw[:1].isupper() and raw.endswith((".", "?", "!"))


@functools.lru_cache(maxsize=2048)
def _strip_figure_refs(text):
    """Drop "(Figure 6-1)" and the like before a quote is matched.

    The model leaves figure references out when it copies, and the book puts
    them mid-sentence. Matching with them removed keeps "Storage is the
    cornerstone ... and underlies its major stages" whole; otherwise the
    longest copied run starts after the parenthetical. Both sides are stripped,
    so a quote that keeps its "(Figure 8-8)" still matches.
    """
    return FIGURE_REFERENCE.sub(" ", text or "")


@functools.lru_cache(maxsize=2048)
def _punctuation_plain(text):
    return " ".join(_NON_WORD_OR_UNDERSCORE_RE.sub(" ", (text or "").lower()).split())


def _quote_in_passage(quote, text):
    if not quote:
        return False
    folded_quote = re.sub(r"\s+", " ", _strip_figure_refs(quote)).lower()
    folded_text = re.sub(r"\s+", " ", _strip_figure_refs(text)).lower()
    if folded_quote in folded_text:
        return True
    # Typographic variants are the same sentence: the book writes curly quotes
    # and interior commas that a copied quote flattens (measured: "data about
    # data", 2026-10-13). Punctuation is not wording; word order is kept.
    return (
        _punctuation_plain(_strip_figure_refs(quote))
        in _punctuation_plain(_strip_figure_refs(text))
    )


def _original_case(span, text):
    """The span as it is written in the passage, case and all, snapped to whole-word boundaries."""
    if not span or not text:
        return span or ""
    flat = re.sub(r"\s+", " ", text or "")
    match = re.search(re.escape(span), flat, re.I)
    if not match:
        return span
    start, end = match.start(), match.end()
    while start > 0 and (flat[start - 1].isalnum() or flat[start - 1] in "-_"):
        start -= 1
    while end < len(flat) and (flat[end].isalnum() or flat[end] in "-_"):
        end += 1
    snapped = flat[start:end].strip(" .")
    return snapped if snapped else span


def longest_copied_span(completion, passage):
    """The longest word-for-word run the model copied. The edit is dropped.

    Under 40 characters is not a quote. Short overlap stays a refusal.
    """
    folded_passage = _fold(passage)
    folded_completion = _fold(completion)
    if not folded_passage or not folded_completion:
        return ""
    match = difflib.SequenceMatcher(
        None, folded_passage, folded_completion, autojunk=False
    ).find_longest_match(0, len(folded_passage), 0, len(folded_completion))
    if match.size < SPAN_MIN_CHARS:
        return ""
    return folded_passage[match.a:match.a + match.size].strip(" .")


def _span_from_chapter(chapter, completion, passages):
    best = ("", None)
    for hit in passages:
        if str(hit["chapter"]) != str(chapter):
            continue
        span = longest_copied_span(completion, hit.get("text") or "")
        if len(span) > len(best[0]):
            best = (span, hit)
    if best[1] is None:
        return None, ""
    snapped = _original_case(best[0], best[1].get("text") or "")
    return best[1], snapped


DANGLING_END_WORDS = frozenset({
    "on", "of", "in", "to", "for", "with", "by", "at", "from", "the", "a", "an",
    "and", "or", "as", "not", "simply", "large", "into", "such", "than", "that",
    "which", "is", "are",
})


def _complete_truncated_quote(quote: str, passage_text: str) -> str:
    """Complete a quote if it was cut off mid-sentence or has unbalanced parentheses."""
    if not quote or not passage_text:
        return quote
    q = quote.strip()
    pos = passage_text.find(q)
    if pos == -1:
        idx = passage_text.lower().find(q.lower())
        if idx != -1:
            q = passage_text[idx:idx + len(q)]
            pos = idx
        else:
            return quote

    unbalanced_parens = q.count("(") > q.count(")")
    words_q = re.findall(r"\b[A-Za-z0-9_-]+\b", q)
    last_word = words_q[-1].lower() if words_q else ""
    ends_dangling = (last_word in DANGLING_END_WORDS) or bool(re.search(r"[,;:\-—–]\s*$", q))

    if not unbalanced_parens and not ends_dangling:
        return quote

    start_pos = pos
    if q and q[0].islower() and start_pos > 0 and (unbalanced_parens or ends_dangling):
        prev_text = passage_text[:start_pos]
        m = list(re.finditer(r'(?<=[.!?\n])\s+', prev_text))
        if m:
            cand_start = m[-1].end()
            if start_pos - cand_start < 80:
                start_pos = cand_start

    open_parens = q.count("(") - q.count(")")
    cur = pos + len(q)
    n = len(passage_text)
    while cur < n:
        ch = passage_text[cur]
        if ch == "(":
            open_parens += 1
        elif ch == ")":
            open_parens -= 1
        elif ch in ".!?\n":
            if open_parens <= 0:
                cur += 1
                while cur < n and passage_text[cur] in '"\'”’)':
                    cur += 1
                completed = passage_text[start_pos:cur].strip()
                if len(completed) <= PARAGRAPH_CAP:
                    return completed
                break
        cur += 1

    return q


def _tagless_citation(text, passages):
    """A verified citation from a reply that forgot the [Ch. tag, or None.

    Whole text verbatim in a shown passage first (case kept), else the longest
    word-for-word span across the shown passages. No gloss: without the tag
    there is no marker for where prose ends and the quote begins.
    """
    quote = _strip_quotes(text)
    hit = _matching_passage_anywhere(quote, passages)
    if hit is not None and (
        len(quote) >= SPAN_MIN_CHARS or _short_sentence(text, quote)
    ):
        quote = _complete_truncated_quote(quote, hit.get("text") or "")
        return {
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        }
    best = ("", None)
    for hit in passages:
        span = longest_copied_span(text, hit.get("text") or "")
        if len(span) > len(best[0]):
            best = (span, hit)
    if best[1] is None:
        return None
    snapped = _original_case(best[0], best[1].get("text") or "")
    snapped = _complete_truncated_quote(snapped, best[1].get("text") or "")
    return {
        "chunk_id": best[1]["chunk_id"],
        "chapter": str(best[1]["chapter"]),
        "quote": snapped,
    }


def _matching_passage(chapter, quote, passages):
    for hit in passages:
        if str(hit["chapter"]) != str(chapter):
            continue
        if _quote_in_passage(quote, hit["text"]):
            return hit
    return None


def _matching_passage_anywhere(quote, passages):
    """A verbatim quote from any attached passage is still a true quote.

    The model's [Ch. N] tag can slip when the matching passage sits last in
    a list of mostly one chapter (measured 2026-10-12: tagged [Ch. 1] for a
    ch04 sentence). The answer's chapter is rebuilt from the matched hit.
    """
    for hit in passages:
        if _quote_in_passage(quote, hit["text"]):
            return hit
    return None


def _reground_alphanumeric_quote(quote, question, chunk_text):
    """Ensure quotes for normal forms, SCD types, acronyms, and attributions align to the exact form asked."""
    q_low = (question or "").lower()
    text = chunk_text or ""
    if "3nf" in q_low or "third normal form" in q_low:
        if "1nf" in quote.lower() and "transitive" not in quote.lower() and "2nf" not in quote.lower():
            for sent in _sentences(text):
                if ("transitive" in sent.lower() or "2nf" in sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif "2nf" in q_low or "second normal form" in q_low:
        if "transitive" in quote.lower() or "single value" in quote.lower():
            for sent in _sentences(text):
                if ("partial" in sent.lower() or "1nf" in sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif "1nf" in q_low or "first normal form" in q_low:
        if "partial" in quote.lower() or "transitive" in quote.lower():
            for sent in _sentences(text):
                if ("single value" in sent.lower() or "primary key" in sent.lower()) and "partial" not in sent.lower() and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif _TYPE_2_RE.search(q_low):
        if "type 3" in quote.lower() or ("type 2" not in quote.lower() and "type-2" not in quote.lower() and "effective end date" not in quote.lower()):
            for sent in _sentences(text):
                sent_low = sent.lower()
                if ("type 2" in sent_low or "type-2" in sent_low) and ("new record" in sent_low or "history" in sent_low or "inserted" in sent_low or "full history" in sent_low):
                    return _complete_truncated_quote(sent, text)
                if "keep a full history of dimension records" in sent_low or ("effective end date" in sent_low and "new record" in sent_low):
                    return _complete_truncated_quote(sent, text)
    elif _S3_RE.search(q_low):
        if not any(k in quote.lower() for k in ("object", "amazon", "cloud", "storage")):
            for sent in _sentences(text):
                sent_low = sent.lower()
                if "s3" in sent_low and any(k in sent_low for k in ("amazon", "object", "cloud", "storage")):
                    return _complete_truncated_quote(sent, text)
    elif _IOPS_RE.search(q_low):
        if "per second" not in quote.lower() and "input/output" not in quote.lower():
            for sent in _sentences(text):
                sent_low = sent.lower()
                if "iops" in sent_low and any(k in sent_low for k in ("per second", "input/output", "operations", "bottleneck", "limitation")):
                    return _complete_truncated_quote(sent, text)
    elif _SLA_SLO_RE.search(q_low):
        if not _SLA_SLO_RE.search(quote.lower()):
            for sent in _sentences(text):
                if _SLA_SLO_RE.search(sent.lower()) and len(sent) >= 30:
                    return _complete_truncated_quote(sent, text)
    elif _WHO_CREATED_RE.search(q_low):
        has_author_name = bool(_AUTHOR_NAME_RE.search(quote))
        if not has_author_name:
            for sent in _sentences(text):
                sent_low = sent.lower()
                if any(w in sent_low for w in _ATTRIBUTION_MARKERS):
                    if _AUTHOR_NAME_RE.search(sent):
                        return _complete_truncated_quote(sent, text)
    return _complete_truncated_quote(quote, text)


def _citation_from_line(stripped, text, passages):
    match = re.match(r"\[Ch\.\s*([^\]]+)\]\s*(.*)", stripped)
    if not match:
        return None, False
    chapter = match.group(1).strip().rstrip(".")
    rest = match.group(2)
    quoted = re.search(r"[\"“](.+?)[\"”]", rest)
    raw = quoted.group(1) if quoted else rest
    quote = _strip_quotes(raw)
    if len(quote) < SPAN_MIN_CHARS and not _short_sentence(raw, quote):
        quote = ""
    hit = _matching_passage(chapter, quote, passages)
    if hit is None:
        hit = _matching_passage_anywhere(quote, passages)
    if hit is None:
        hit, quote = _span_from_chapter(chapter, rest, passages)
    if hit is None:
        hit, quote = _span_from_chapter(chapter, text, passages)
    if hit is None:
        return None, True
    quote = _complete_truncated_quote(quote, hit.get("text") or "")
    return {
        "chunk_id": hit["chunk_id"],
        "chapter": str(hit["chapter"]),
        "quote": quote,
    }, False


def _parse_citations(text, passages):
    if not text.startswith("[Ch."):
        citation = _tagless_citation(text, passages)
        if citation is None:
            return None
        return [citation], []
    citations = []
    gloss = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        citation, failed = _citation_from_line(stripped, text, passages)
        if failed:
            return None
        if citation is None:
            gloss.append(stripped)
        else:
            citations.append(citation)
    return citations, gloss


def _passage_for_id(passages, chunk_id):
    return next((p for p in passages if p.get("chunk_id") == chunk_id), None)


def _expand_to_paragraphs(citations, passages, anchors, question):
    is_process_q = bool(re.search(r"\bhow\s+(?:does|do|can)\b", question or "", re.I))
    if not (anchors or is_process_q):
        return
    for item in citations:
        spot = _passage_for_id(passages, item["chunk_id"])
        if spot is None:
            continue
        paragraph = _paragraph_around(item["quote"], spot.get("text") or "")
        if anchors and _whole_paragraph(anchors, paragraph, item["quote"]):
            item["quote"] = paragraph
        elif is_process_q and paragraph and len(paragraph) <= PARAGRAPH_CAP and len(paragraph) >= SPAN_MIN_CHARS:
            item["quote"] = paragraph


def _trim_citations(citations, passages, question):
    for item in citations:
        spot = _passage_for_id(passages, item["chunk_id"])
        if spot is not None:
            item["quote"] = _without_heading(item["quote"], spot)
            item["quote"] = _reground_alphanumeric_quote(
                item["quote"], question, spot.get("text", "")
            )


_COMPARISON_PRONOUNS = frozenset({"this", "it", "that", "they", "these", "those"})
_CONTRAST_MARKERS = ("unlike", "versus", "vs.", "vs", "difference between", "differ from", "differ", "compared to", "in contrast")


def _side_matches(is_pronoun, tokens, text, combine):
    if is_pronoun:
        return True
    return combine(re.search(rf"\b{re.escape(stem(t))}\w*\b", text) for t in tokens)


def _expand_pair_quote(sents, i, s, p, p_text):
    s_cand = _without_heading(s, p)
    if len(s_cand) >= 100:
        return s_cand
    if i > 0:
        prev_s = _without_heading(sents[i - 1], p)
        if len(prev_s) + 1 + len(s_cand) <= PARAGRAPH_CAP and _quote_in_passage(f"{prev_s} {s_cand}", p_text):
            return f"{prev_s} {s_cand}"
    elif i + 1 < len(sents):
        next_s = _without_heading(sents[i + 1], p)
        if len(s_cand) + 1 + len(next_s) <= PARAGRAPH_CAP and _quote_in_passage(f"{s_cand} {next_s}", p_text):
            return f"{s_cand} {next_s}"
    return s_cand


def _comparison_sentence(p, p_text, left_pr, right_pr, tokens_left, tokens_right):
    s_best = None
    sents = _candidate_sentences(p_text, p.get("heading") or "")
    for i, s in enumerate(sents):
        s_low = s.lower()
        in_left = _side_matches(left_pr, tokens_left, s_low, any)
        in_right = _side_matches(right_pr, tokens_right, s_low, any)
        if in_left and in_right:
            if len(s) >= SPAN_MIN_CHARS:
                s_best = _expand_pair_quote(sents, i, s, p, p_text)
                break
        elif (in_left or in_right) and any(m in s_low for m in ("unlike", "difference", "versus", "differ")):
            if len(s) >= SPAN_MIN_CHARS and not s_best:
                s_best = _without_heading(s, p)
    if not s_best:
        s_best = _without_heading(p_text.split("\n\n")[0], p)
    return s_best


def _best_dual_passage(passages, left_pr, right_pr, tokens_left, tokens_right):
    dual_hit = None
    dual_sentence = None
    best_contrast_score = -1
    for p in passages:
        p_text = p.get("text") or ""
        p_low = p_text.lower()
        if not (_side_matches(left_pr, tokens_left, p_low, all) and _side_matches(right_pr, tokens_right, p_low, all)):
            continue
        c_score = 1
        for marker in _CONTRAST_MARKERS:
            if marker in p_low:
                c_score += 5
        body_start = p_text.split("\n", 1)[1].strip() if "\n" in p_text else p_text
        if body_start.startswith("("):
            c_score -= 10
        if c_score > best_contrast_score:
            s_best = _comparison_sentence(p, p_text, left_pr, right_pr, tokens_left, tokens_right)
            if s_best:
                best_contrast_score = c_score
                dual_hit = p
                dual_sentence = s_best
    return dual_hit, dual_sentence


def _align_comparison(citations, passages, question):
    sides = _comparison_sides(question)
    if not (sides and len(passages) >= 1):
        return citations
    left_pr = sides[0].lower() in _COMPARISON_PRONOUNS
    right_pr = sides[1].lower() in _COMPARISON_PRONOUNS
    tokens_left = [] if left_pr else _side_tokens(sides[0])
    tokens_right = [] if right_pr else _side_tokens(sides[1])
    if not ((tokens_left or left_pr) and (tokens_right or right_pr)):
        return citations
    dual_hit, dual_sentence = _best_dual_passage(passages, left_pr, right_pr, tokens_left, tokens_right)
    if not (dual_hit and dual_sentence):
        return citations
    cur_quote = citations[0]["quote"].lower() if citations else ""
    cur_has_left = _side_matches(left_pr, tokens_left, cur_quote, any)
    cur_has_right = _side_matches(right_pr, tokens_right, cur_quote, any)
    if not (cur_has_left and cur_has_right) or dual_hit["chunk_id"] != citations[0]["chunk_id"]:
        return [{
            "chunk_id": dual_hit["chunk_id"],
            "chapter": str(dual_hit["chapter"]),
            "quote": dual_sentence,
        }]
    return citations


def _assemble_body(citations, gloss, passages, figures):
    answer_lines = [
        f"[Ch. {item['chapter']}] \"{item['quote']}\"" for item in citations
    ]
    if gloss:
        gloss_cleaned = _clean_boilerplate_gloss(" ".join(gloss))
        if gloss_cleaned:
            answer_lines.append(gloss_cleaned)
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited] or passages
    return {
        "answer": "\n".join(answer_lines),
        "citations": citations,
        "figures": figures_for(named, figures or []),
        "refused": False,
    }


def parse_completion(completion, passages, figures=None, anchors=None, question=""):
    """Return a contract body. Unchecked prose is a refusal.

    A figure is attached only when a passage the answer cited names it. When
    the paragraph around a verified quote holds an anchor word and fits
    PARAGRAPH_CAP, the paragraph replaces the quote; paragraph text is passage
    text, so the quote check holds by construction.
    """
    text = (completion or "").strip()
    if text == REFUSAL:
        return _refusal(passages, figures)

    parsed = _parse_citations(text, passages)
    if parsed is None or not parsed[0]:
        return _refusal(passages, figures)
    citations, gloss = parsed
    _expand_to_paragraphs(citations, passages, anchors, question)
    _trim_citations(citations, passages, question)
    citations = _align_comparison(citations, passages, question)
    body = _assemble_body(citations, gloss, passages, figures)
    return _align_citation_to_query_concepts(body, question, passages)


def _heading_text(p):
    return ((p.get("heading") or "") + " " + (p.get("text") or "")).lower()


def _current_text(passages, cur_chunk_id):
    cur_hit = _passage_for_id(passages, cur_chunk_id)
    return _heading_text(cur_hit) if cur_hit else ""


def _single_citation_body(p, quote, body):
    chap = str(p["chapter"])
    return {
        "answer": f'[Ch. {chap}] "{quote}"\n{quote}',
        "citations": [{
            "chunk_id": p["chunk_id"],
            "chapter": chap,
            "quote": quote,
        }],
        "figures": figures_for([p], body.get("figures") or []),
        "refused": False,
    }


def _first_matching_sentence(p, predicate):
    for s in _sentences(p.get("text") or ""):
        s_clean = _without_heading(s, p)
        if predicate(s_clean):
            return s_clean
    return None


def _acronym_sentence(best_hit, primary_ac, question):
    b_text = best_hit.get("text") or ""
    best_sent = ""
    for ac in primary_ac:
        for s in _sentences(b_text):
            s_clean = _without_heading(s, best_hit)
            if re.search(rf"\b{re.escape(ac)}s?\b", s_clean.lower()) and len(s_clean) >= SPAN_MIN_CHARS:
                best_sent = s_clean
                break
        if best_sent:
            break
    if not best_sent:
        for ac in primary_ac:
            para = _paragraph_around(ac, b_text)
            if para and len(para) <= PARAGRAPH_CAP and len(para) >= SPAN_MIN_CHARS:
                best_sent = _without_heading(para, best_hit)
                break
    if best_sent:
        best_sent = _reground_alphanumeric_quote(best_sent, question, b_text)
    return best_sent


def _best_acronym_passage(passages, q_acronyms, primary_ac):
    best_hit = None
    best_count = -100
    for p in passages:
        p_text = _heading_text(p)
        head_text = (p.get("heading") or "").lower()
        is_example = head_text.startswith("example:") or head_text.startswith("example ")
        count = sum(2 if ac in primary_ac else 1 for ac in q_acronyms if re.search(rf"\b{re.escape(ac)}s?\b", p_text))
        if is_example:
            count -= 3
        if count > best_count:
            best_count = count
            best_hit = p
    return best_hit


def _align_to_acronyms(body, question, passages, cur_chunk_id):
    raw_acronyms = [w.lower() for w in re.findall(r"\b[A-Za-z0-9]+\b", question) if (w.isupper() and len(w) >= 2) or w.lower() in ("s3", "iops", "aimd", "sla", "slo", "cdc")]
    q_acronyms = sorted(raw_acronyms, key=lambda a: (0 if a in ("tcp", "ip", "udp") else 1, len(a)), reverse=True)
    if not q_acronyms:
        return None, [], False
    cur_text = _current_text(passages, cur_chunk_id)
    primary_ac = [ac for ac in q_acronyms if ac not in ("tcp", "ip", "udp")] or q_acronyms
    cur_has_acronym = any(re.search(rf"\b{re.escape(ac)}s?\b", cur_text) for ac in primary_ac)
    if "iops" in primary_ac and cur_chunk_id != passages[0].get("chunk_id"):
        p0_text = (passages[0].get("text") or "").lower()
        if "operations per second" in p0_text and "operations per second" not in cur_text:
            cur_has_acronym = False
    if cur_has_acronym:
        return None, primary_ac, cur_has_acronym
    best_hit = _best_acronym_passage(passages, q_acronyms, primary_ac)
    if best_hit:
        best_sent = _acronym_sentence(best_hit, primary_ac, question)
        if best_sent:
            return _single_citation_body(best_hit, best_sent, body), primary_ac, cur_has_acronym
    return None, primary_ac, cur_has_acronym


def _align_to_content_verbs(body, question, passages, cur_chunk_id):
    content_verbs = [w.lower() for w in words(question) if w.lower() in ("extract", "extracting", "replicate", "ingest")]
    if not content_verbs:
        return None
    if any(v in _current_text(passages, cur_chunk_id) for v in content_verbs):
        return None
    for p in passages:
        if any(v in _heading_text(p) for v in content_verbs):
            s_clean = _first_matching_sentence(
                p, lambda s: any(v in s.lower() for v in content_verbs) and len(s) >= SPAN_MIN_CHARS
            )
            if s_clean is not None:
                return _single_citation_body(p, s_clean, body)
    return None


def _align_to_top_phrase(body, question, passages, cur_chunk_id, primary_ac, cur_has_acronym):
    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question.lower())
    phrases = []
    for i in range(len(tokens) - 1):
        w1, w2 = tokens[i], tokens[i + 1]
        if w1 not in STOPWORDS and w1 not in STEM_WORDS and len(w1) >= 3:
            if w2 not in STOPWORDS and w2 not in STEM_WORDS and len(w2) >= 3:
                phrases.append(f"{w1} {w2}")
    if not (phrases and passages and cur_chunk_id != passages[0].get("chunk_id") and not (primary_ac and cur_has_acronym)):
        return None
    cur_text = _current_text(passages, cur_chunk_id)
    top_text = _heading_text(passages[0])
    matched_phrase = next((ph for ph in phrases if re.search(rf"\b{re.escape(ph)}\b", top_text)), None)
    if not matched_phrase or re.search(rf"\b{re.escape(matched_phrase)}\b", cur_text):
        return None
    p = passages[0]
    s_clean = _first_matching_sentence(
        p, lambda s: re.search(rf"\b{re.escape(matched_phrase)}\b", s.lower()) and len(s) >= SPAN_MIN_CHARS
    )
    if s_clean is not None:
        return _single_citation_body(p, s_clean, body)
    return None


def _align_to_creator(body, question, passages, citations):
    if not re.search(r"\bwho\s+(?:created|invented|designed|developed|authored|introduced|wrote|founded|proposed)\b", question, re.I):
        return None
    cur_quote = citations[0].get("quote", "") if citations else ""
    has_author = bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", cur_quote)) or any(w in cur_quote.lower() for w in ("author", "creator", "created", "invented", "wrote", "book"))
    if has_author:
        return None
    for p in passages:
        s_clean = _first_matching_sentence(
            p,
            lambda s: len(s) >= SPAN_MIN_CHARS
            and re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", s)
            and any(w in s.lower() for w in ("noted", "book", "article", "creator", "created", "invented", "introduced", "proposed", "authored")),
        )
        if s_clean is not None:
            return _single_citation_body(p, s_clean, body)
    return None


def _reground_current_citation(body, question, passages, cur_chunk_id):
    citations = body["citations"]
    cur_hit = _passage_for_id(passages, cur_chunk_id)
    if not cur_hit:
        return
    cur_q = citations[0].get("quote", "")
    regrounded = _reground_alphanumeric_quote(cur_q, question, cur_hit.get("text", ""))
    if regrounded and regrounded != cur_q:
        citations[0]["quote"] = regrounded
        lines = (body.get("answer") or "").splitlines()
        if lines and lines[0].startswith("[Ch."):
            lines[0] = f'[Ch. {citations[0]["chapter"]}] "{regrounded}"'
            body["answer"] = "\n".join(lines)


def _align_citation_to_query_concepts(body, question, passages):
    """Realign citations to passages that actually discuss the query's core acronyms or topic concepts."""
    if not body or body.get("refused") or not body.get("citations") or not passages:
        return body
    citations = body["citations"]
    cur_chunk_id = citations[0].get("chunk_id")

    realigned, primary_ac, cur_has_acronym = _align_to_acronyms(body, question, passages, cur_chunk_id)
    if realigned is None:
        realigned = _align_to_content_verbs(body, question, passages, cur_chunk_id)
    if realigned is None:
        realigned = _align_to_top_phrase(body, question, passages, cur_chunk_id, primary_ac, cur_has_acronym)
    if realigned is None:
        realigned = _align_to_creator(body, question, passages, citations)
    if realigned is not None:
        return realigned

    _reground_current_citation(body, question, passages, cur_chunk_id)
    return body


def _refusal(passages, figures=None):
    misses = []
    for hit in passages[:3]:
        snippet = re.sub(r"\s+", " ", hit.get("text") or "").strip()
        misses.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": snippet[:MISS_QUOTE_CHARS],
        })
    return {
        "answer": REFUSAL,
        "citations": misses,
        "figures": figures_for(passages[:3], figures or []),
        "refused": True,
        "followups": [],
    }
