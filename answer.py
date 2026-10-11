"""Quote-first answers from retrieved passages. Phase 4. No new routes.

The model quotes. This module checks the quote is in the passage.
A failed check is a refusal. It is never a free answer.
"""

import json
import random
import re
import urllib.request

from figures import figures_for
from prompt import ANSWER_MODEL, REFUSAL, SYSTEM
from retrieve import search

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
PASSAGE_LIMIT = 5
MISS_QUOTE_CHARS = 160
FORMAT_REMINDER = (
    "Copy one sentence from a passage. Do not reword it.\n"
    "Format example, not an answer:\n"
    "[Ch. 2] \"exact sentence copied from a passage\"\n"
    "One short line in simple words."
)
QUIZ_INSTRUCTION = (
    "Write one question a person could answer with a quote from the single "
    "passage below. Do not include that quote in the question. "
    "Do not start with [Ch. The question is one or two sentences."
)
KEY_MIN_CHARS = 40


def passages_block(passages):
    blocks = []
    for hit in passages:
        blocks.append(
            f"[Ch. {hit['chapter']}] chunk_id={hit['chunk_id']}\n{hit['text']}"
        )
    return "\n\n".join(blocks)


def user_message(question, passages):
    return (
        f"Question: {question}\n\n"
        "Passages:\n"
        f"{passages_block(passages)}\n\n"
        f"{FORMAT_REMINDER}"
    )


def ollama_generate(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT, timeout=120):
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    message = body.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("empty completion")
    return content.strip()


def _strip_quotes(text):
    text = text.strip()
    text = text.strip("\"'`“”")
    return re.sub(r"\s+", " ", text).strip(" .")


def _quote_in_passage(quote, text):
    if not quote:
        return False
    folded_quote = re.sub(r"\s+", " ", quote).lower()
    folded_text = re.sub(r"\s+", " ", text).lower()
    return folded_quote in folded_text


def _matching_passage(chapter, quote, passages):
    for hit in passages:
        if str(hit["chapter"]) != str(chapter):
            continue
        if _quote_in_passage(quote, hit["text"]):
            return hit
    return None


def parse_completion(completion, passages, figures=None):
    """Return a contract body. Unchecked prose is a refusal.

    A figure is attached only when a kept passage names it.
    """
    text = (completion or "").strip()
    if text == REFUSAL:
        return _refusal(passages, figures)
    if not text.startswith("[Ch."):
        return _refusal(passages, figures)

    citations = []
    gloss = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"\[Ch\.\s*([^\]]+)\]\s*(.*)", stripped)
        if not match:
            gloss.append(stripped)
            continue
        chapter = match.group(1).strip().rstrip(".")
        rest = match.group(2)
        quoted = re.search(r"[\"“](.+?)[\"”]", rest)
        quote = _strip_quotes(quoted.group(1) if quoted else rest)
        hit = _matching_passage(chapter, quote, passages)
        if hit is None:
            return _refusal(passages, figures)
        citations.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        })
    if not citations:
        return _refusal(passages, figures)
    answer_lines = [
        f"[Ch. {item['chapter']}] \"{item['quote']}\"" for item in citations
    ]
    if gloss:
        answer_lines.append(" ".join(gloss))
    return {
        "answer": "\n".join(answer_lines),
        "citations": citations,
        "figures": figures_for(passages, figures or []),
        "refused": False,
    }


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
    }


def ask(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL):
    search_fn = search_fn or search
    generate_fn = generate_fn or ollama_generate
    passages = search_fn(index, question, k=PASSAGE_LIMIT)
    if not passages:
        return _refusal([])
    completion = generate_fn(SYSTEM, user_message(question, passages), model)
    return parse_completion(completion, passages, index.get("figures") or [])


def explain(index, selection, generate_fn=None, search_fn=None, model=ANSWER_MODEL):
    """The highlight is the question. The neighborhood is the passages."""
    if not (selection or "").strip():
        raise ValueError("missing selection")
    return ask(index, selection.strip(), generate_fn, search_fn, model)


def _sentences(text):
    raw = (text or "").strip()
    lines = raw.splitlines()
    if len(lines) > 1 and not lines[0].strip().endswith((".", "?", "!")):
        raw = "\n".join(lines[1:])
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", raw).strip())
    sentences = []
    for part in parts:
        sentence = part.strip()
        if len(sentence) < KEY_MIN_CHARS:
            continue
        if sentence[0].isupper() and sentence.endswith((".", "?", "!")):
            sentences.append(sentence)
    return sentences


def pick_quiz_chunk(index, rng=None):
    """One real teaching chunk. Not a part title. Not the index."""
    rng = rng or random.Random()
    usable = []
    for chunk in index.get("chunks") or []:
        if not str(chunk.get("chapter", "")).isdigit():
            continue
        if _sentences(chunk.get("text") or ""):
            usable.append(chunk)
    if not usable:
        return None
    return rng.choice(usable)


def quiz(index, generate_fn=None, model=ANSWER_MODEL, rng=None, chunk=None):
    """One question. The key is one sentence from one chunk. No score.

    The question must not contain the key. A leak is a refusal.
    """
    generate_fn = generate_fn or ollama_generate
    chunk = chunk or pick_quiz_chunk(index, rng)
    if chunk is None:
        return _refusal([])
    sentences = _sentences(chunk.get("text") or "")
    if not sentences:
        return _refusal([])
    key = sentences[0]
    user = (
        f"{QUIZ_INSTRUCTION}\n\n"
        f"[Ch. {chunk['chapter']}] chunk_id={chunk['chunk_id']}\n"
        f"{chunk['text']}"
    )
    completion = generate_fn(SYSTEM, user, model).strip()
    if not completion or completion == REFUSAL or "[Ch." in completion:
        return _refusal([chunk], index.get("figures") or [])
    if _quote_in_passage(key, completion) or key.lower() in completion.lower():
        return _refusal([chunk], index.get("figures") or [])
    return {
        "answer": completion,
        "citations": [{
            "chunk_id": chunk["chunk_id"],
            "chapter": str(chunk["chapter"]),
            "quote": key,
        }],
        "figures": figures_for([chunk], index.get("figures") or []),
        "refused": False,
    }
