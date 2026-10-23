import re

from engine.answering.context import _patch_figures_src, _should_include_chunk_figures
from engine.answering.freeanswer import _tokens
from engine.answering.generate import ollama_generate
from engine.answering.gloss import (
    _gloss_repeats_quote,
    _has_content_word_overlap,
    _is_coherent_gloss,
    _synthesize_grounded_gloss,
)
from engine.answering.intent import analyze_intent, compute_dynamic_followups
from engine.answering.messages import _explain_gloss_user_message
from engine.answering.prompt import ANSWER_MODEL, EXPLAIN_GLOSS_SYSTEM
from engine.answering.quoteask import ask
from engine.answering.quotecheck import _quote_in_passage, _refusal
from engine.answering.sanitize import is_prompt_injection, sanitize_query
from engine.answering.shared import (
    _anchor_sentence_for_selection,
    _candidate_sentences,
    _clean_boilerplate_gloss,
    chunk_by_id,
    chunk_position,
)
from engine.figures import figures_for


def highlight_query(selection, heading=""):
    """The question a highlight means.

    A sentence is already a question for search. A word or a short phrase is
    not: "splashed" and "because" retrieve neighbor chapters. Those become
    "What is …?", the same rewrite canonical_query uses for a typed label,
    with the heading so the search knows which "time" the reader marked.
    """
    text = (selection or "").strip()
    if not text:
        return text
    words = text.split()
    if len(words) > 6 or text.endswith((".", "?", "!")):
        return text
    heading = (heading or "").strip()
    if heading and heading.lower() not in text.lower():
        return f"What is {text} in {heading}?"
    return f"What is {text}?"


def _cross_chunk_quotes(chunk1, chunk2, selection):
    """Extract boundary quotes from chunk1 and chunk2 for a cross-chunk selection."""
    if not chunk1 or not chunk2:
        return None, None
    text1 = chunk1.get("text") or ""
    text2 = chunk2.get("text") or ""
    cands1 = _candidate_sentences(text1, chunk1.get("heading") or "")
    cands2 = _candidate_sentences(text2, chunk2.get("heading") or "")
    if not cands1 or not cands2:
        return None, None

    sel = (selection or "").strip().lower()
    words_list = sel.split()
    q1 = None
    q2 = None
    if len(words_list) >= 2:
        for split_pt in range(1, len(words_list)):
            part1 = " ".join(words_list[:split_pt])
            part2 = " ".join(words_list[split_pt:])
            if part1 in text1.lower() and part2 in text2.lower():
                a1 = _anchor_sentence_for_selection(chunk1, part1)
                a2 = _anchor_sentence_for_selection(chunk2, part2)
                if a1 and a2:
                    return a1, a2
                if a1 and not q1:
                    q1 = a1
                if a2 and not q2:
                    q2 = a2

    if not q1:
        q1 = cands1[-1]
    if not q2:
        q2 = cands2[0]
    return q1, q2


def explain(index, selection, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
            chunk_id=None, heading="", end_chunk_id=None, embed_fn=None):
    """The highlight is the question. The neighborhood is the passages.

    A short highlight is asked as a question. The chunk the reader selected
    stays in the passages even when dense search prefers another chapter.
    """
    if is_prompt_injection(selection):
        return _refusal([])
    selection = sanitize_query(selection)
    if not (selection or "").strip():
        raise ValueError("missing selection")
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    pin_chunk_obj = None
    end_chunk_obj = None
    neighbors = []
    chunks = index.get("chunks") or []
    if chunk_id:
        i = chunk_position(index, chunk_id)
        if i is not None:
            c = chunks[i]
            pin_chunk_obj = c
            if i > 0 and chunks[i - 1].get("chapter") == c.get("chapter"):
                neighbors.append(chunks[i - 1])
            if i + 1 < len(chunks) and chunks[i + 1].get("chapter") == c.get("chapter"):
                neighbors.append(chunks[i + 1])

    if end_chunk_id:
        end_chunk_obj = chunk_by_id(index, end_chunk_id)
        if end_chunk_obj and end_chunk_obj not in neighbors and end_chunk_obj != pin_chunk_obj:
            neighbors.append(end_chunk_obj)

    intent_info = analyze_intent(selection, heading, pin_chunk_obj, neighbors) if pin_chunk_obj else {}
    anchor_quote = None
    quote2 = None
    sec_chunk_obj = end_chunk_obj
    chosen_chunk = pin_chunk_obj

    if pin_chunk_obj is not None:
        anchor_quote = intent_info.get("anchor_sentence") or _anchor_sentence_for_selection(pin_chunk_obj, selection)
        chosen_chunk = intent_info.get("chosen_chunk") or pin_chunk_obj

        if anchor_quote is None or (sec_chunk_obj and selection.lower() not in (pin_chunk_obj.get("text") or "").lower()):
            if sec_chunk_obj:
                q1, q2 = _cross_chunk_quotes(pin_chunk_obj, sec_chunk_obj, selection)
                if q1:
                    anchor_quote = q1
                    quote2 = q2
                if sec_chunk_obj not in neighbors and sec_chunk_obj != pin_chunk_obj:
                    neighbors.append(sec_chunk_obj)

        if anchor_quote:
            if not _quote_in_passage(anchor_quote, chosen_chunk.get("text") or ""):
                found_chunk = None
                if _quote_in_passage(anchor_quote, pin_chunk_obj.get("text") or ""):
                    found_chunk = pin_chunk_obj
                else:
                    for n in neighbors:
                        if n and _quote_in_passage(anchor_quote, n.get("text") or ""):
                            found_chunk = n
                            break
                if found_chunk:
                    chosen_chunk = found_chunk

        if is_live and anchor_quote:
            quote = anchor_quote
            quote_for_prompt = f"{quote} {quote2}" if quote2 else quote
            gloss_prompt = _explain_gloss_user_message(selection, quote_for_prompt, chosen_chunk, neighbors)
            try:
                raw_gloss = generate_fn(EXPLAIN_GLOSS_SYSTEM, gloss_prompt, model)
            except Exception:
                raw_gloss = ""

            cleaned_gloss = (raw_gloss or "").strip()
            if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
            cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
            cleaned_gloss = cleaned_gloss.strip("\"'“”")
            cleaned_gloss = _clean_boilerplate_gloss(cleaned_gloss, selection)
            if not _is_coherent_gloss(cleaned_gloss, quote_for_prompt) or _gloss_repeats_quote(cleaned_gloss, quote_for_prompt) or (
                intent_info.get("is_passing_mention")
                and not _has_content_word_overlap(cleaned_gloss, quote_for_prompt, exclude=f"{selection} {chosen_chunk.get('heading', '')}")
            ):
                cleaned_gloss = _synthesize_grounded_gloss(selection, quote_for_prompt, chosen_chunk, neighbors, generate_fn, model)
            if cleaned_gloss:
                if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                    cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
                cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
                cleaned_gloss = cleaned_gloss.strip("\"'“”")

            chapter = str(chosen_chunk.get("chapter", ""))
            citations = [{
                "chunk_id": chosen_chunk.get("chunk_id") or chunk_id,
                "chapter": chapter,
                "quote": quote,
                "doc": chosen_chunk.get("source", ""),
            }]
            if quote2 and sec_chunk_obj:
                c2_chap = str(sec_chunk_obj.get("chapter", ""))
                citations.append({
                    "chunk_id": sec_chunk_obj.get("chunk_id"),
                    "chapter": c2_chap,
                    "quote": quote2,
                    "doc": sec_chunk_obj.get("source", ""),
                })
                answer_text = f'[Ch. {chapter}] "{quote}"\n[Ch. {c2_chap}] "{quote2}"\n{cleaned_gloss}'
            else:
                answer_text = f'[Ch. {chapter}] "{quote}"\n{cleaned_gloss}'

            if _should_include_chunk_figures(chosen_chunk, selection, quote, index.get("figures") or []):
                figures_pool = [chosen_chunk]
                if sec_chunk_obj and quote2:
                    figures_pool.append(sec_chunk_obj)
            else:
                figures_pool = [{"text": f"{selection} {quote} {quote2 or ''}"}]
            figures = figures_for(figures_pool, index.get("figures") or [])
            return {
                "answer": answer_text,
                "refused": False,
                "citations": citations,
                "figures": figures,
                "followups": compute_dynamic_followups(
                    chosen_chunk, neighbors, selection=selection,
                    question=selection, answer_text=answer_text, mode="explain"
                ),
            }

    question = highlight_query(selection, heading)
    body = ask(
        index, question, generate_fn, search_fn, model,
        canonical=False, pin_chunk=chunk_id, end_chunk_id=end_chunk_id,
        embed_fn=embed_fn,
    )

    if pin_chunk_obj is not None and anchor_quote:
        valid_sents = set(_candidate_sentences(pin_chunk_obj.get("text") or "", pin_chunk_obj.get("heading") or ""))
        valid_ask = False
        if not body.get("refused") and body.get("citations"):
            first_cite = body["citations"][0]
            cite_id = first_cite.get("chunk_id")
            cite_quote = first_cite.get("quote", "")
            has_sel = selection.lower() in cite_quote.lower()
            answer_lines = [line.strip() for line in (body.get("answer") or "").splitlines() if line.strip()]
            has_gloss = False
            if len(answer_lines) >= 2 and not selection.strip().endswith("?"):
                second_line = answer_lines[1]
                norm_second = re.sub(r"[\s\"'“”]+", " ", second_line).strip().lower()
                norm_quote = re.sub(r"[\s\"'“”]+", " ", cite_quote).strip().lower()
                new_words = _tokens(second_line) - _tokens(cite_quote)
                if (norm_second and norm_second != norm_quote
                        and len(norm_second) > 25 and len(new_words) >= 3):
                    has_gloss = True
            if (cite_id == chunk_id and has_sel and has_gloss and not quote2 and
                    (not valid_sents or cite_quote in valid_sents)):
                valid_ask = True

        if valid_ask:
            answer_lines = [line.strip() for line in (body.get("answer") or "").splitlines() if line.strip()]
            if len(answer_lines) >= 2:
                cleaned_second = _clean_boilerplate_gloss(answer_lines[1], selection)
                if not _is_coherent_gloss(cleaned_second, anchor_quote):
                    cleaned_second = _synthesize_grounded_gloss(selection, anchor_quote, chosen_chunk, neighbors, generate_fn, model)
                body["answer"] = f"{answer_lines[0]}\n{cleaned_second}"
            if not body.get("refused"):
                body["followups"] = compute_dynamic_followups(
                    chosen_chunk, neighbors, selection=selection,
                    question=selection, answer_text=body.get("answer", ""), mode="explain"
                )
            else:
                body["followups"] = []
            return _patch_figures_src(body, index)

        quote = anchor_quote
        if (not body.get("refused") and body.get("citations") and
                body["citations"][0].get("chunk_id") == chunk_id and not quote2):
            cand_quote = body["citations"][0].get("quote", "")
            if (selection.lower() in cand_quote.lower() and
                    _quote_in_passage(cand_quote, pin_chunk_obj.get("text", "")) and
                    (not valid_sents or cand_quote in valid_sents) and
                    len(cand_quote) >= 40):
                quote = cand_quote

        if quote and not _quote_in_passage(quote, chosen_chunk.get("text") or ""):
            found_chunk = None
            if _quote_in_passage(quote, pin_chunk_obj.get("text") or ""):
                found_chunk = pin_chunk_obj
            else:
                for n in neighbors:
                    if n and _quote_in_passage(quote, n.get("text") or ""):
                        found_chunk = n
                        break
            if found_chunk:
                chosen_chunk = found_chunk

        quote_for_prompt = f"{quote} {quote2}" if quote2 else quote
        gloss_prompt = _explain_gloss_user_message(selection, quote_for_prompt, chosen_chunk, neighbors)
        try:
            raw_gloss = generate_fn(EXPLAIN_GLOSS_SYSTEM, gloss_prompt, model)
        except Exception:
            raw_gloss = ""

        cleaned_gloss = (raw_gloss or "").strip()
        if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
            cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
        cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
        cleaned_gloss = cleaned_gloss.strip("\"'“”")
        cleaned_gloss = _clean_boilerplate_gloss(cleaned_gloss, selection)
        if not _is_coherent_gloss(cleaned_gloss, quote_for_prompt) or _gloss_repeats_quote(cleaned_gloss, quote_for_prompt):
            cleaned_gloss = _synthesize_grounded_gloss(selection, quote_for_prompt, chosen_chunk, neighbors, generate_fn, model)
        if cleaned_gloss:
            if re.match(r"^\[ch\.", cleaned_gloss, re.I) and "\n" in cleaned_gloss:
                cleaned_gloss = cleaned_gloss.split("\n", 1)[1].strip()
            cleaned_gloss = re.sub(r"\[Ch\.\s*[^\]]+\]\s*", "", cleaned_gloss, flags=re.I).strip()
            cleaned_gloss = cleaned_gloss.strip("\"'“”")

        chapter = str(chosen_chunk.get("chapter", ""))
        citations = [{
            "chunk_id": chosen_chunk.get("chunk_id") or chunk_id,
            "chapter": chapter,
            "quote": quote,
            "doc": chosen_chunk.get("source", ""),
        }]
        if quote2 and sec_chunk_obj:
            c2_chap = str(sec_chunk_obj.get("chapter", ""))
            citations.append({
                "chunk_id": sec_chunk_obj.get("chunk_id"),
                "chapter": c2_chap,
                "quote": quote2,
                "doc": sec_chunk_obj.get("source", ""),
            })
            answer_text = f'[Ch. {chapter}] "{quote}"\n[Ch. {c2_chap}] "{quote2}"\n{cleaned_gloss}'
        else:
            answer_text = f'[Ch. {chapter}] "{quote}"\n{cleaned_gloss}'

        if _should_include_chunk_figures(chosen_chunk, selection, quote, index.get("figures") or []):
            figures_pool = [chosen_chunk]
            if sec_chunk_obj and quote2:
                figures_pool.append(sec_chunk_obj)
        else:
            figures_pool = [{"text": f"{selection} {quote} {quote2 or ''}"}]
        figures = figures_for(figures_pool, index.get("figures") or [])
        return _patch_figures_src({
            "answer": answer_text,
            "refused": False,
            "citations": citations,
            "figures": figures,
            "followups": compute_dynamic_followups(
                chosen_chunk, neighbors, selection=selection,
                question=selection, answer_text=answer_text, mode="explain"
            ),
        }, index)

    if not body.get("refused"):
        body["followups"] = compute_dynamic_followups(
            chosen_chunk, neighbors, selection=selection,
            question=selection, answer_text=body.get("answer", ""), mode="explain"
        )
    else:
        body["followups"] = []
    return _patch_figures_src(body, index)
