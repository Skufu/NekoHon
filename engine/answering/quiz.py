import random

from engine.answering.canonical import STEM_WORDS
from engine.answering.generate import ollama_generate
from engine.answering.intent import compute_dynamic_followups
from engine.answering.prompt import ANSWER_MODEL, REFUSAL, SYSTEM
from engine.answering.quotecheck import quote_in_passage, refusal_response
from engine.answering.indexmaps import chunk_by_id
from engine.answering.sentences import cached_words, split_sentences
from engine.retrieval.preprocess import stem, STOPWORDS
from engine.figures import figures_for


QUIZ_INSTRUCTION = (
    "Write one question a person could answer with a quote from the single "
    "passage below. Do not include that quote in the question. "
    "Do not start with [Ch. The question is one or two sentences."
)


QUIZ_SYSTEM = (
    "You are a teacher testing a reader's comprehension of a book. "
    "Write exactly one question whose answer is the target sentence. "
    "Do not include [Ch. N] tags, do not quote the sentence verbatim, and do not refuse."
)


WEAK_QUIZ_PREFIXES = (
    "Behind the scenes", "For example", "For instance", "As we discussed",
    "As mentioned", "In this chapter", "In the next chapter", "Let's look",
    "See Figure", "See Chapter", "Up to this point",
)


def quiz_sentences(text):
    sents = split_sentences(text)
    if not sents:
        return []
    filtered = [
        s for s in sents
        if not any(s.strip().startswith(prefix) for prefix in WEAK_QUIZ_PREFIXES)
    ]
    return filtered if filtered else sents


def pick_quiz_chunk(index, rng=None):
    rng = rng or random.Random()
    usable = []
    for chunk in index.get("chunks") or []:
        if not str(chunk.get("chapter", "")).isdigit():
            continue
        if quiz_sentences(chunk.get("text") or ""):
            usable.append(chunk)
    if not usable:
        return None
    return rng.choice(usable)


def _chunk_with_sentences(index, chunk_id, rng):
    chunks = index.get("chunks") or []
    found_chunk = chunk_by_id(index, chunk_id)
    if found_chunk is None:
        return None
    if quiz_sentences(found_chunk.get("text") or ""):
        return found_chunk
    try:
        idx = chunks.index(found_chunk)
        for offset in (1, -1, 2, -2):
            cand_idx = idx + offset
            if 0 <= cand_idx < len(chunks):
                cand = chunks[cand_idx]
                if cand.get("chapter") == found_chunk.get("chapter") and quiz_sentences(cand.get("text") or ""):
                    return cand
    except ValueError:
        pass
    chapter_chunks = [
        c for c in chunks
        if c.get("chapter") == found_chunk.get("chapter") and quiz_sentences(c.get("text") or "")
    ]
    return rng.choice(chapter_chunks) if chapter_chunks else None


def _leaks_key(key, completion):
    return quote_in_passage(key, completion) or key.lower() in completion.lower()


def _content_stems(text):
    return {
        stem(w.lower()) for w in cached_words(text)
        if len(w) > 2 and w.lower() not in STOPWORDS and w.lower() not in STEM_WORDS
    }


def _needs_quiz_retry(comp, key, chunk):
    if not comp or comp == REFUSAL or "[Ch." in comp:
        return True
    if _leaks_key(key, comp):
        return True
    key_content = _content_stems(key + " " + (chunk.get("heading") or ""))
    q_stems = _content_stems(comp.splitlines()[0].strip())
    return bool(key_content and not (key_content & q_stems))


def _retry_completion(generate_fn, model, key, chunk, completion):
    retry_user = (
        f"{QUIZ_INSTRUCTION}\n\n"
        f"Target answer sentence (write a question that is directly answered by this specific sentence):\n"
        f'"{key}"\n\n'
        f"Topic: {chunk.get('heading', '')}"
    )
    try:
        retry_comp = generate_fn(QUIZ_SYSTEM, retry_user, model).strip()
        if retry_comp and retry_comp != REFUSAL and "[Ch." not in retry_comp:
            if not _leaks_key(key, retry_comp):
                return retry_comp
    except Exception:
        pass
    return completion


def quiz(index, generate_fn=None, model=ANSWER_MODEL, rng=None, chunk=None,
         chunk_id=None):
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    rng = rng or random.Random()
    chunks = index.get("chunks") or []
    if chunk is None and chunk_id:
        chunk = _chunk_with_sentences(index, chunk_id, rng)
    chunk = chunk or pick_quiz_chunk(index, rng)
    if chunk is None:
        return refusal_response([])
    sentences = quiz_sentences(chunk.get("text") or "")
    if not sentences:
        return refusal_response([])
    key = rng.choice(sentences)
    user = (
        f"{QUIZ_INSTRUCTION}\n\n"
        f"Target answer sentence (write a question that is directly answered by this specific sentence without repeating it):\n"
        f'"{key}"\n\n'
        f"Passage:\n"
        f"{chunk['text']}"
    )
    completion = generate_fn(SYSTEM, user, model).strip()

    if is_live and _needs_quiz_retry(completion, key, chunk):
        completion = _retry_completion(generate_fn, model, key, chunk, completion)

    if not completion or completion == REFUSAL or "[Ch." in completion or _leaks_key(key, completion):
        return refusal_response([chunk], index.get("figures") or [])

    quiz_neighbors = []
    if chunk in chunks:
        idx = chunks.index(chunk)
        if idx + 1 < len(chunks):
            quiz_neighbors.append(chunks[idx + 1])

    return {
        "answer": completion,
        "citations": [{
            "chunk_id": chunk["chunk_id"],
            "chapter": str(chunk["chapter"]),
            "quote": key,
        }],
        "figures": figures_for([chunk], index.get("figures") or []),
        "refused": False,
        "followups": compute_dynamic_followups(
            chunk, neighbors=quiz_neighbors, question=completion, answer_text=key, mode="quiz"
        ),
    }
