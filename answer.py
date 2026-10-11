"""Quote-first answers from retrieved passages. Phase 4. No new routes.

The model quotes. This module checks the quote is in the passage.
A failed check is a refusal. It is never a free answer.
"""

import json
import re
import urllib.request

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


def parse_completion(completion, passages):
    """Return a contract body. Unchecked prose is a refusal.

    figures stays empty. Showing an image is Phase 5.
    """
    text = (completion or "").strip()
    if text == REFUSAL:
        return _refusal(passages)
    if not text.startswith("[Ch."):
        return _refusal(passages)

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
            return _refusal(passages)
        citations.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": quote,
        })
    if not citations:
        return _refusal(passages)
    answer_lines = [
        f"[Ch. {item['chapter']}] \"{item['quote']}\"" for item in citations
    ]
    if gloss:
        answer_lines.append(" ".join(gloss))
    return {
        "answer": "\n".join(answer_lines),
        "citations": citations,
        "figures": [],
        "refused": False,
    }


def _refusal(passages):
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
        "figures": [],
        "refused": True,
    }


def ask(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL):
    search_fn = search_fn or search
    generate_fn = generate_fn or ollama_generate
    passages = search_fn(index, question, k=PASSAGE_LIMIT)
    if not passages:
        return _refusal([])
    completion = generate_fn(SYSTEM, user_message(question, passages), model)
    return parse_completion(completion, passages)
