import random

from engine.answering.canonical import STEM_WORDS
from engine.answering.generate import ollama_generate
from engine.answering.intent import compute_dynamic_followups
from engine.answering.prompt import ANSWER_MODEL, REFUSAL, SYSTEM
from engine.answering.quotecheck import _quote_in_passage, _refusal
from engine.answering.shared import _sentences, chunk_by_id, stem, words
from engine.figures import figures_for
from engine.retrieval.preprocess import STOPWORDS


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
    sents = _sentences(text)
    if not sents:
        return []
    filtered = [
        s for s in sents
        if not any(s.strip().startswith(prefix) for prefix in WEAK_QUIZ_PREFIXES)
    ]
    return filtered if filtered else sents


def pick_quiz_chunk(index, rng=None):
    """One real teaching chunk. Not a part title. Not the index."""
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


def quiz(index, generate_fn=None, model=ANSWER_MODEL, rng=None, chunk=None,
         chunk_id=None):
    """One question. The key is one sentence from one chunk. No score.

    The question must not contain the key. A leak is a refusal.
    """
    is_live = (generate_fn is None) or bool(getattr(generate_fn, "_is_live", False))
    generate_fn = generate_fn or ollama_generate
    rng = rng or random.Random()
    chunks = index.get("chunks") or []
    if chunk is None and chunk_id:
        found_chunk = chunk_by_id(index, chunk_id)
        if found_chunk is not None:
            if quiz_sentences(found_chunk.get("text") or ""):
                chunk = found_chunk
            else:
                try:
                    idx = chunks.index(found_chunk)
                    for offset in (1, -1, 2, -2):
                        cand_idx = idx + offset
                        if 0 <= cand_idx < len(chunks):
                            cand = chunks[cand_idx]
                            if cand.get("chapter") == found_chunk.get("chapter") and quiz_sentences(cand.get("text") or ""):
                                chunk = cand
                                break
                except ValueError:
                    pass
                if chunk is None:
                    chapter_chunks = [
                        c for c in chunks
                        if c.get("chapter") == found_chunk.get("chapter") and quiz_sentences(c.get("text") or "")
                    ]
                    if chapter_chunks:
                        chunk = rng.choice(chapter_chunks)
    chunk = chunk or pick_quiz_chunk(index, rng)
    if chunk is None:
        return _refusal([])
    sentences = quiz_sentences(chunk.get("text") or "")
    if not sentences:
        return _refusal([])
    key = rng.choice(sentences)
    user = (
        f"{QUIZ_INSTRUCTION}\n\n"
        f"Target answer sentence (write a question that is directly answered by this specific sentence without repeating it):\n"
        f'"{key}"\n\n'
        f"Passage:\n"
        f"{chunk['text']}"
    )
    completion = generate_fn(SYSTEM, user, model).strip()

    if is_live:
        def _needs_quiz_retry(comp):
            if not comp or comp == REFUSAL or "[Ch." in comp:
                return True
            if _quote_in_passage(key, comp) or key.lower() in comp.lower():
                return True
            q_line = comp.splitlines()[0].strip()
            key_content = {
                stem(w.lower()) for w in words(key + " " + (chunk.get("heading") or ""))
                if len(w) > 2 and w.lower() not in STOPWORDS and w.lower() not in STEM_WORDS
            }
            q_stems = {
                stem(w.lower()) for w in words(q_line)
                if len(w) > 2 and w.lower() not in STOPWORDS and w.lower() not in STEM_WORDS
            }
            if key_content and not (key_content & q_stems):
                return True
            return False

        if _needs_quiz_retry(completion):
            retry_user = (
                f"{QUIZ_INSTRUCTION}\n\n"
                f"Target answer sentence (write a question that is directly answered by this specific sentence):\n"
                f'"{key}"\n\n'
                f"Topic: {chunk.get('heading', '')}"
            )
            try:
                retry_comp = generate_fn(QUIZ_SYSTEM, retry_user, model).strip()
                if retry_comp and retry_comp != REFUSAL and "[Ch." not in retry_comp:
                    if not (_quote_in_passage(key, retry_comp) or key.lower() in retry_comp.lower()):
                        completion = retry_comp
            except Exception:
                pass

    if not completion or completion == REFUSAL or "[Ch." in completion:
        return _refusal([chunk], index.get("figures") or [])
    if _quote_in_passage(key, completion) or key.lower() in completion.lower():
        return _refusal([chunk], index.get("figures") or [])

    quiz_neighbors = []
    if chunk in chunks:
        try:
            idx = chunks.index(chunk)
            if idx + 1 < len(chunks):
                quiz_neighbors.append(chunks[idx + 1])
        except ValueError:
            pass

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
