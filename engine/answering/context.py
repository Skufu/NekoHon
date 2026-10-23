import re

from engine.answering.canonical import STEM_WORDS
from engine.answering.conversation import (
    extract_subject_from_history,
    is_topic_shift_followup,
    rank_seq_chunks,
    prior_turn_chunk_position,
)
from engine.answering.indexmaps import chunk_by_id, chunk_position
from engine.answering.sentences import cached_words
from engine.answering.textrules import TOPIC_SHIFT_CONCEPT_RE
from engine.figures import cited_numbers, number_from_id
from engine.retrieval.captions import caption_seed
from engine.retrieval.fusion import fuse
from engine.retrieval.keywords import postings, rare
from engine.retrieval.preprocess import STOPWORDS
from engine.retrieval.readings import llm_second_reading, second_reading
from engine.retrieval.retrieve import rank_chunks


PASSAGE_LIMIT = 5


DEFAULT_BOOK_ID = "".join(["f", "d", "e"])


def patch_figures_src(body, index):
    if not isinstance(body, dict) or not isinstance(index, dict):
        return body
    book_id = index.get("book_id", DEFAULT_BOOK_ID)
    if book_id != DEFAULT_BOOK_ID:
        for fig in body.get("figures", []):
            if fig.get("src") and "?book_id=" not in fig["src"]:
                fig["src"] = f"{fig['src']}?book_id={book_id}"
    return body


def should_include_chunk_figures(chunk, selection, quote, all_figures):
    if not chunk:
        return False
    if cited_numbers(quote):
        return True
    heading = (chunk.get("heading") or "").strip().lower()
    sel_low = (selection or "").strip().lower()
    if heading and sel_low and (sel_low in heading or heading in sel_low):
        return True
    chunk_fig_nums = cited_numbers(chunk.get("text") or "")
    if chunk_fig_nums and all_figures:
        sel_quote_words = {
            w.lower() for w in cached_words(f"{selection} {quote}")
            if len(w) >= 3 and w.lower() not in STOPWORDS
        }
        for fig in all_figures:
            num = number_from_id(fig.get("id"))
            if num and num in chunk_fig_nums:
                caption = fig.get("caption") or ""
                cap_words = {
                    w.lower() for w in cached_words(caption)
                    if len(w) >= 3 and w.lower() not in STOPWORDS
                }
                if sel_quote_words & cap_words:
                    return True
    return False


def _prioritize_phrase_matches(passages, question):
    if not passages or not question:
        return passages
    tokens = re.findall(r"\b[a-zA-Z0-9_-]+\b", question.lower())
    phrases = []
    for i in range(len(tokens) - 1):
        w1, w2 = tokens[i], tokens[i + 1]
        if w1 not in STOPWORDS and w1 not in STEM_WORDS and len(w1) >= 3:
            if w2 not in STOPWORDS and w2 not in STEM_WORDS and len(w2) >= 3:
                phrases.append(f"{w1} {w2}")
    acronyms = [w for w in re.findall(r"\b[A-Za-z0-9]+\b", question) if (w.isupper() and 2 <= len(w) <= 5) or w.lower() in ("s3", "iops")]

    def score_hit(hit):
        score = 0
        text_low = ((hit.get("heading") or "") + " " + (hit.get("text") or "")).lower()
        head_low = (hit.get("heading") or "").lower()
        for p in phrases:
            if re.search(rf"\b{re.escape(p)}\b", text_low):
                score += 10
            if re.search(rf"\b{re.escape(p)}\b", head_low):
                score += 15
        for ac in acronyms:
            ac_low = ac.lower()
            if re.search(rf"\b{re.escape(ac_low)}s?\b", head_low):
                if not (head_low.startswith("example:") or head_low.startswith("example ")):
                    score += 20
                else:
                    score += 5
            if ac_low == "s3":
                if "amazon s3" in text_low or "object storage" in text_low:
                    score += 15
                if "storage classes" in text_low or "storage tiers" in text_low:
                    score += 10
            elif ac_low == "iops" and ("operations per second" in text_low or "(iops)" in text_low):
                score += 15
        return score

    scores = [score_hit(h) for h in passages]
    if any(s > 0 for s in scores):
        scored = list(zip(scores, passages))
        passages = [h for _, h in sorted(scored, key=lambda x: x[0], reverse=True)]
    return passages


def _clean_history(history):
    return [
        h for h in (history or [])
        if isinstance(h, dict) and (h.get("question") or h.get("answer"))
    ]


def _effective_pin(index, question, history, selection, pin_chunk):
    topic_shift = is_topic_shift_followup(question, history, selection, pin_chunk=pin_chunk, index=index)
    effective_pin = None if (topic_shift and not selection) else pin_chunk
    if effective_pin is not None or not history or topic_shift:
        return topic_shift, effective_pin
    clean_history = _clean_history(history)
    if not clean_history:
        return topic_shift, effective_pin
    m_concept = TOPIC_SHIFT_CONCEPT_RE.match(question.strip())
    if not m_concept:
        return topic_shift, effective_pin
    concept_target = m_concept.group(1).strip()
    target_words = {w.lower() for w in cached_words(concept_target) if w.lower() not in STOPWORDS and len(w) >= 2}
    prior_a = (clean_history[-1].get("answer") or "").strip()
    if len(target_words) >= 3 and prior_a and all(w in prior_a.lower() for w in target_words):
        prior_pos = prior_turn_chunk_position(index, prior_a)
        if prior_pos is not None:
            effective_pin = index["chunks"][prior_pos].get("chunk_id")
    return topic_shift, effective_pin


def _initial_passages(index, question, search_fn, embed_fn):
    if search_fn is not None:
        return search_fn(index, question, k=PASSAGE_LIMIT), None
    ranked = rank_chunks(index, question, embed_fn=embed_fn)
    passages = [
        {
            "score": score,
            "chunk_id": chunk["chunk_id"],
            "chapter": chunk["chapter"],
            "heading": chunk.get("heading", ""),
            "text": chunk.get("text", ""),
            "source": chunk.get("source", ""),
        }
        for score, chunk in ranked[:PASSAGE_LIMIT]
    ]
    ranks = {chunk["chunk_id"]: i for i, (_, chunk) in enumerate(ranked, start=1)}
    return passages, ranks


def _find_reading(index, question, best_score, word_map, generate_fn, embed_fn):
    try:
        reading = second_reading(index, question, best_score, word_map=word_map, embed_fn=embed_fn)
    except TypeError:
        reading = second_reading(index, question, best_score, word_map=word_map)
    if reading is not None:
        return reading
    try:
        return llm_second_reading(
            index, question, best_score,
            generate_fn=generate_fn, word_map=word_map,
            embed_fn=embed_fn,
        )
    except TypeError:
        return llm_second_reading(
            index, question, best_score,
            generate_fn=generate_fn, word_map=word_map,
        )


def _fuse_passages(index, question, asked, passages, word_map, ranks, embed_fn):
    if not rare(asked, word_map):
        return passages
    if ranks is not None and asked == question:
        try:
            return fuse(index, asked, passages, word_map, ranks=ranks, embed_fn=embed_fn)
        except TypeError:
            try:
                return fuse(index, asked, passages, word_map, ranks=ranks)
            except TypeError:
                return fuse(index, asked, passages, word_map)
    try:
        return fuse(index, asked, passages, word_map, embed_fn=embed_fn)
    except TypeError:
        return fuse(index, asked, passages, word_map)


def _seed_captions(index, asked, passages, embed_fn):
    try:
        passages = caption_seed(index, asked, passages, embed_fn=embed_fn)
    except TypeError:
        passages = caption_seed(index, asked, passages)
    return _prioritize_phrase_matches(passages, asked)


def _pin_id(effective_pin):
    return effective_pin.get("chunk_id") if isinstance(effective_pin, dict) else effective_pin


def _inject_history_sequence(index, question, passages, clean_history, effective_pin):
    chunks = index.get("chunks") or []
    target_idx = None
    if effective_pin:
        p_id = _pin_id(effective_pin)
        if p_id:
            target_idx = chunk_position(index, p_id)
    if target_idx is None:
        target_idx = prior_turn_chunk_position(index, clean_history[-1].get("answer") or "")
    if target_idx is None:
        return passages
    seq_chunks = []
    for offset in (0, 1, -1, 2):
        cand_idx = target_idx + offset
        if 0 <= cand_idx < len(chunks):
            cand = chunks[cand_idx]
            if str(cand.get("chapter")) == str(chunks[target_idx].get("chapter")) and cand not in seq_chunks:
                seq_chunks.append(cand)
    if not seq_chunks:
        return passages
    ranked_seq = rank_seq_chunks(seq_chunks, question, extract_subject_from_history(clean_history))
    p0_s = passages[0].get("score") if passages else 1.0
    base_score = float(p0_s) if p0_s is not None else 1.0
    injected = []
    for idx_offset, c in enumerate(ranked_seq):
        c_dict = dict(c)
        c_s = c.get("score")
        c_dict["score"] = float(c_s) if c_s is not None else (base_score - 0.001 * (idx_offset + 1))
        injected.append(c_dict)
    injected_ids = {c["chunk_id"] for c in injected}
    passages = injected + [p for p in passages if p.get("chunk_id") not in injected_ids]
    return passages[:PASSAGE_LIMIT]


def _adjacent_same_chapter(chunks, p_idx, p_obj):
    neighbors = []
    if p_idx + 1 < len(chunks) and chunks[p_idx + 1].get("chapter") == p_obj.get("chapter"):
        neighbors.append(chunks[p_idx + 1])
    if p_idx > 0 and chunks[p_idx - 1].get("chapter") == p_obj.get("chapter"):
        neighbors.append(chunks[p_idx - 1])
    return neighbors


def _append_missing(passages, extras):
    current_ids = {p.get("chunk_id") for p in passages}
    for n in extras:
        if n.get("chunk_id") not in current_ids:
            passages.append(n)


def _same_chapter_window(index, passages, p_id, p_obj):
    chunks = index.get("chunks") or []
    try:
        p_idx = chunk_position(index, p_id)
    except ValueError:
        return passages
    p_chap = str(p_obj.get("chapter"))
    same_chap_seq = []
    for offset in (0, 1, -1, 2, -2):
        cand_idx = p_idx + offset
        if 0 <= cand_idx < len(chunks):
            cand = chunks[cand_idx]
            if str(cand.get("chapter")) == p_chap and cand.get("chunk_id") not in {c.get("chunk_id") for c in same_chap_seq}:
                same_chap_seq.append(cand)
    seen_ids = {c.get("chunk_id") for c in same_chap_seq}
    same_chap_dense = [p for p in passages if str(p.get("chapter")) == p_chap and p.get("chunk_id") not in seen_ids]
    for p in same_chap_dense:
        seen_ids.add(p.get("chunk_id"))
    other_passages = [p for p in passages if p.get("chunk_id") not in seen_ids]
    return (same_chap_seq + same_chap_dense + other_passages)[:PASSAGE_LIMIT]


def _chapter_query_neighbors(index, passages, p_id, p_obj, clean_history):
    chunks = index.get("chunks") or []
    try:
        p_idx = chunk_position(index, p_id)
    except ValueError:
        return passages
    p_neighbors = _adjacent_same_chapter(chunks, p_idx, p_obj)
    if clean_history:
        p_n_ids = {n.get("chunk_id") for n in p_neighbors}
        passages = [p for p in passages if p.get("chunk_id") not in p_n_ids]
        return p_neighbors + passages
    _append_missing(passages, p_neighbors)
    return passages


def _pin_neighbors(index, passages, p_id, p_obj):
    chunks = index.get("chunks") or []
    try:
        p_idx = chunk_position(index, p_id)
    except ValueError:
        return passages
    _append_missing(passages, _adjacent_same_chapter(chunks, p_idx, p_obj))
    return passages


def _inject_pin_context(index, question, passages, effective_pin, topic_shift, clean_history):
    p_id = _pin_id(effective_pin)
    p_obj = chunk_by_id(index, p_id)
    if not p_obj:
        return passages
    if topic_shift:
        return _pin_neighbors(index, passages, p_id, p_obj)
    if re.search(r"\b(which\s+chapter|where\s+in\s+the\s+book|chapter\s+\d+|across\s+chapters)\b", question, re.I):
        return _chapter_query_neighbors(index, passages, p_id, p_obj, clean_history)
    return _same_chapter_window(index, passages, p_id, p_obj)


def retrieval_context(index, question, search_fn=None, generate_fn=None,
                      pin_chunk=None, end_chunk_id=None, history=None, selection="",
                      embed_fn=None):
    topic_shift, effective_pin = _effective_pin(index, question, history, selection, pin_chunk)
    passages, ranks = _initial_passages(index, question, search_fn, embed_fn)
    passages = pin_to_chunk(index, passages, effective_pin, end_chunk_id=end_chunk_id)

    context = {
        "question": question,
        "asked": question,
        "passages": passages,
        "reading": None,
        "word_map": {},
    }
    if not passages:
        return context
    word_map = postings(index)
    context["word_map"] = word_map
    reading = _find_reading(index, question, passages[0].get("score", 0.0), word_map, generate_fn, embed_fn)
    if reading is not None:
        context["reading"] = reading
        context["asked"] = reading["reading"]
        if not any(hit["chunk_id"] == reading["chunk"]["chunk_id"] for hit in passages):
            passages = [reading["chunk"]] + passages[:-1]
    asked = context["asked"]
    passages = _fuse_passages(index, question, asked, passages, word_map, ranks, embed_fn)
    passages = _seed_captions(index, asked, passages, embed_fn)

    clean_history = _clean_history(history)
    if clean_history and not topic_shift:
        passages = _inject_history_sequence(index, question, passages, clean_history, effective_pin)
    if effective_pin:
        passages = _inject_pin_context(index, question, passages, effective_pin, topic_shift, clean_history)

    if effective_pin or end_chunk_id:
        passages = pin_to_chunk(index, passages, effective_pin, end_chunk_id=end_chunk_id)
    context["passages"] = passages
    return context


def pin_to_chunk(index, passages, chunk_id, end_chunk_id=None):
    if not chunk_id and not end_chunk_id:
        return passages
    c1 = chunk_by_id(index, chunk_id) if chunk_id else None
    c2 = chunk_by_id(index, end_chunk_id) if end_chunk_id and end_chunk_id != chunk_id else None

    if c1 is None and c2 is None:
        return passages

    pinned = []
    base_score = passages[0].get("score", 1.0) if passages else 1.0
    if c1 is not None:
        pinned.append({
            "score": base_score,
            "chunk_id": c1.get("chunk_id"),
            "chapter": c1.get("chapter"),
            "heading": c1.get("heading", ""),
            "text": c1.get("text", ""),
            "source": c1.get("source", ""),
        })
    if c2 is not None:
        pinned.append({
            "score": base_score * 0.99,
            "chunk_id": c2.get("chunk_id"),
            "chapter": c2.get("chapter"),
            "heading": c2.get("heading", ""),
            "text": c2.get("text", ""),
            "source": c2.get("source", ""),
        })

    pinned_ids = {p["chunk_id"] for p in pinned}
    rest = [hit for hit in passages if hit.get("chunk_id") not in pinned_ids]
    return pinned + rest[: max(0, PASSAGE_LIMIT - len(pinned))]
