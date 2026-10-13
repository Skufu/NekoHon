"""Quote-first answers from retrieved passages. Phase 4. No new routes.

The model quotes. This module checks the quote is in the passage.
A failed check is a refusal. It is never a free answer.
"""

import difflib
import json
import random
import re
import urllib.request

from captions import caption_seed
from figures import figures_for
from fusion import fuse
from keywords import anchor_words, postings, rare
from prompt import ANSWER_MODEL, REFUSAL, SYSTEM
from readings import second_reading
from retrieve import search

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
PASSAGE_LIMIT = 5
MISS_QUOTE_CHARS = 160
FIGURE_REFERENCE = re.compile(r"\((?:figure|fig\.)\s*[A-Za-z]?\d+-\d+\)", re.I)
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
SPAN_MIN_CHARS = 40
# A complete sentence may answer even when shorter than SPAN_MIN_CHARS:
# "Everything fails, all the time." is 30 characters. Sentence shape is the
# test; a fragment or a bare heading stays a refusal.
MIN_QUOTE_CHARS = 20
# One screen of quoted text (about 16 lines at 75 chars). A paragraph over this
# keeps the model's quote instead of the whole paragraph. Chosen for
# readability; not tuned to any ask.
PARAGRAPH_CAP = 1200


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


def _strip_figure_refs(text):
    """Drop "(Figure 6-1)" and the like before a quote is matched.

    The model leaves figure references out when it copies, and the book puts
    them mid-sentence. Matching with them removed keeps "Storage is the
    cornerstone ... and underlies its major stages" whole; otherwise the
    longest copied run starts after the parenthetical. Both sides are stripped,
    so a quote that keeps its "(Figure 8-8)" still matches.
    """
    return FIGURE_REFERENCE.sub(" ", text or "")


def _quote_in_passage(quote, text):
    if not quote:
        return False
    folded_quote = re.sub(r"\s+", " ", _strip_figure_refs(quote)).lower()
    folded_text = re.sub(r"\s+", " ", _strip_figure_refs(text)).lower()
    return folded_quote in folded_text


def _fold(text):
    return re.sub(r"\s+", " ", text or "").lower()


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
    return best[1], best[0]


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
    return {
        "chunk_id": best[1]["chunk_id"],
        "chapter": str(best[1]["chapter"]),
        "quote": best[0],
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


def _paragraph_around(quote, passage_text):
    """The passage paragraph that holds the quote, whitespace-normalized."""
    folded = _fold(quote)
    if not folded:
        return ""
    for paragraph in re.split(r"\n\s*\n", passage_text or ""):
        if folded in _fold(paragraph):
            return re.sub(r"\s+", " ", paragraph).strip()
    return ""


def _whole_paragraph(anchors, paragraph):
    """True when the paragraph around a verified quote replaces it.

    The paragraph must hold an anchor word — a question word the book itself
    counts as rare (`keywords.anchor_words`), so there is no English list-word
    table here — and it must fit PARAGRAPH_CAP, so an answer quote stays about
    one screen. The quote is passage text and the paragraph holds it, so the
    swap can only add book text; the quote check holds by construction.

    The older rule also required the quote to *lack* the anchor, which stopped
    short whenever the model named the question's word but quoted only part of
    the paragraph (measured: the multicloud list, 2026-10-12).
    """
    if not paragraph or len(paragraph) > PARAGRAPH_CAP:
        return False
    folded = _fold(paragraph)
    return any(re.search(rf"\b{re.escape(word)}\b", folded) for word in anchors)


def _without_heading(quote, passage):
    """A quote that opens with the passage's heading line drops it.

    A chunk's first line is its heading, so a model copying across that line
    writes "Insert-Only The insert-only pattern retains history..." or "Key
    considerations for the transformation phase Logically, we treat..." —
    verbatim, but it reads as a fragment.

    The test is what follows the heading: a heading that runs on into its own
    sentence leaves a lowercase remainder ("Modularity allows engineers..."),
    and a heading that was the sentence's subject leaves a bracket or lower case
    ("Modularity (Figure 4-5) is...", "Storage is the cornerstone..."). Only a
    genuine new sentence after the heading — an upper-case start of real length
    — gets the heading dropped.
    """
    heading = (passage.get("text") or "").split("\n", 1)[0].strip()
    words = heading.split()
    if not words:
        return quote
    pattern = r"\s*".join(re.escape(word) for word in words)
    match = re.match(rf"\s*{pattern}[\s:\u2014-]*", quote, re.I)
    if not match:
        return quote
    rest = quote[match.end():].strip()
    if len(rest) < SPAN_MIN_CHARS or not rest[:1].isupper():
        return quote
    return rest


def parse_completion(completion, passages, figures=None, anchors=None):
    """Return a contract body. Unchecked prose is a refusal.

    A figure is attached only when a passage the answer cited names it. When
    the paragraph around a verified quote holds an anchor word and fits
    PARAGRAPH_CAP, the paragraph replaces the quote; paragraph text is passage
    text, so the quote check holds by construction.
    """
    text = (completion or "").strip()
    if text == REFUSAL:
        return _refusal(passages, figures)

    citations = []
    gloss = []
    if not text.startswith("[Ch."):
        # The model sometimes writes the book's own sentence and forgets the
        # tag (measured: "Normalization is a database data modeling practice
        # ...", 2026-10-13). The verification is the same rule as everywhere:
        # verbatim in a shown passage, or a long enough word-for-word span;
        # the tag is rebuilt from the matched passage. Unverified prose is
        # still a refusal.
        citation = _tagless_citation(text, passages)
        if citation is None:
            return _refusal(passages, figures)
        citations.append(citation)
    else:
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
            raw = quoted.group(1) if quoted else rest
            quote = _strip_quotes(raw)
            if len(quote) < SPAN_MIN_CHARS and not _short_sentence(raw, quote):
                quote = ""
            hit = _matching_passage(chapter, quote, passages)
            if hit is None:
                hit = _matching_passage_anywhere(quote, passages)
            if hit is None:
                hit, quote = _span_from_chapter(chapter, rest or text, passages)
            if hit is None:
                return _refusal(passages, figures)
            citations.append({
                "chunk_id": hit["chunk_id"],
                "chapter": str(hit["chapter"]),
                "quote": quote,
            })
    if not citations:
        return _refusal(passages, figures)
    if anchors:
        for item in citations:
            spot = next(
                (hit for hit in passages if hit["chunk_id"] == item["chunk_id"]),
                None,
            )
            if spot is None:
                continue
            paragraph = _paragraph_around(item["quote"], spot.get("text") or "")
            if _whole_paragraph(anchors, paragraph):
                item["quote"] = paragraph
    # One trim, after every path that can set a quote: the anchor expansion
    # above replaces the quote with the whole paragraph, heading line included.
    for item in citations:
        spot = next(
            (hit for hit in passages if hit["chunk_id"] == item["chunk_id"]),
            None,
        )
        if spot is not None:
            item["quote"] = _without_heading(item["quote"], spot)
    answer_lines = [
        f"[Ch. {item['chapter']}] \"{item['quote']}\"" for item in citations
    ]
    if gloss:
        answer_lines.append(" ".join(gloss))
    # Only the passages the answer actually cited may attach a figure. The rest
    # of the kept passages used to ride along, which is how a data-mesh figure
    # appeared on an answer about the MAD landscape.
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited] or passages
    return {
        "answer": "\n".join(answer_lines),
        "citations": citations,
        "figures": figures_for(named, figures or []),
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
    word_map = postings(index)
    # A word the book does not contain may be a typo. One self-proving reading
    # becomes the question when it scores strictly better, and the answer says
    # which reading it answered. Nothing is repaired silently.
    reading = second_reading(index, question, passages[0]["score"], word_map=word_map)
    asked = question
    if reading is not None:
        asked = reading["reading"]
        present = any(
            hit["chunk_id"] == reading["chunk"]["chunk_id"] for hit in passages
        )
        if not present:
            passages = [reading["chunk"]] + passages[:-1]
    # Fusion pays one embed plus a full cosine pass. The lexical channel joins
    # only when the question carries a rare book word, the trigger the boost
    # used; other asks do not pay.
    if rare(asked, word_map):
        passages = fuse(index, asked, passages, word_map)
    # Caption seeding runs last: its measured effect is which chunk leads, and
    # fusion would otherwise be free to demote that lead.
    passages = caption_seed(index, asked, passages)
    completion = generate_fn(SYSTEM, user_message(asked, passages), model)
    anchors = anchor_words(question, word_map)
    body = parse_completion(
        completion, passages, index.get("figures") or [], anchors
    )
    if reading is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{asked}"'
    return body


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
