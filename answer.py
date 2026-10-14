"""Answers from retrieved passages: the ask and answer modes.

ask: the model quotes, the quote is checked; a failed check is a refusal.
answer: the model writes freely from the passages; its [Ch. n] tags become
citations, quotation marks the passages cannot back are stripped, and the
quote check demotes from gate to meter (artifacts/harnesses/groundedness.py).
"""

import difflib
import json
import random
import re
import urllib.request

from canonical import canonical_query
from captions import caption_seed
from figures import figures_for
from fusion import fuse
from keywords import anchor_words, postings, rare
from prompt import ANSWER_MODEL, PARAPHRASE_SYSTEM, REFUSAL, SYSTEM, SYSTEM_ANSWER
from readings import llm_second_reading, second_reading
from retrieve import search

OLLAMA_CHAT = "http://127.0.0.1:11434/api/chat"
PASSAGE_LIMIT = 5
# Rewrites per plain answer: one call each, a call budget, not a quality knob
# (measured citations run at 1-3; the scorecard's answers stayed under five).
PARAPHRASE_LIMIT = 5
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
TAG_PATTERN = re.compile(r"\[Ch\.\s*([^\]]+)\]")
QUOTE_PATTERN = re.compile(r"[\"“]([^\"“”]+)[\"”]")
ANSWER_REMINDER = (
    "Answer the question directly, in your own words. Cite each claim with "
    "[Ch. N] using the chapter of the passage it came from."
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


def answer_user_message(question, passages):
    return (
        f"Question: {question}\n\n"
        "Passages:\n"
        f"{passages_block(passages)}\n\n"
        f"{ANSWER_REMINDER}"
    )


def ollama_generate(system, user, model=ANSWER_MODEL, url=OLLAMA_CHAT, timeout=120):
    # num_predict caps runaway generations: a loop becomes a truncated answer
    # instead of the 120 s client timeout (loop-mechanism-analysis-2026-10-14).
    # 512 is far above the longest legal reply (answer targets p90 622 chars).
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 512},
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


def _punctuation_plain(text):
    return " ".join(re.sub(r"[^\w\s]|_", " ", (text or "").lower()).split())


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


def _plural(word):
    """True when an English word is a regular plural — the list detector.

    Stemming's first step is a suffix rule, not a dictionary; the same works
    here. "disadvantages", "types", "steps", "categories", "batches" pass;
    "endpoint", "analysis", "status", "business", "class" do not. Irregulars
    ("criteria") fall through to the model's own answer, the safe side.
    """
    if len(word) < 4 or word.endswith(("ss", "us", "is", "ous")):
        return False
    if word.endswith("ies"):
        return True
    if word.endswith(("ches", "shes", "xes", "zes", "ses")):
        return True
    return word.endswith("s")


def _whole_paragraph(anchors, paragraph, quote):
    """True when the paragraph around a verified quote replaces it.

    Two triggers, both book-general:
    - the paragraph holds an anchor word the quote lacks: the model quoted
      near the topic without naming it, so the paragraph is the answering
      material;
    - the paragraph holds a plural anchor ("disadvantages", "types",
      "steps"): a plural question wants the kinds of a thing, and the
      paragraph is the book's list (measured: "multicloud methodology
      disadvantages" takes the paragraph while "endpoint" keeps the model's
      sentence, 2026-10-13).
    The paragraph must also fit PARAGRAPH_CAP, so an answer quote stays about
    one screen. The quote is passage text and the paragraph holds it, so the
    swap can only add book text; the quote check holds by construction.
    """
    if not paragraph or len(paragraph) > PARAGRAPH_CAP:
        return False
    folded = _fold(paragraph)
    folded_quote = _fold(quote)
    for word in anchors:
        pattern = rf"\b{re.escape(word)}\b"
        if not re.search(pattern, folded):
            continue
        if _plural(word) or not re.search(pattern, folded_quote):
            return True
    return False


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
            if _whole_paragraph(anchors, paragraph, item["quote"]):
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


def retrieval_context(index, question, search_fn=None, generate_fn=None):
    """The passages the model is shown, after reading, fusion, and seeding.

    Shared by ask and respond so both modes see the same evidence; the
    groundedness meter (artifacts/harnesses/groundedness.py) calls this to compare an
    answer against exactly the passages it was given. When a question word is
    not in the book, the reading repair runs first (difflib, self-proving);
    the LLM enhancer is the fallback under the same gate, so a typo difflib
    cannot see still gets one honest attempt.
    """
    search_fn = search_fn or search
    passages = search_fn(index, question, k=PASSAGE_LIMIT)
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
    # A word the book does not contain may be a typo. One self-proving reading
    # becomes the question when it scores strictly better, and the answer says
    # which reading it answered. Nothing is repaired silently.
    reading = second_reading(index, question, passages[0]["score"], word_map=word_map)
    if reading is None:
        # The difflib reading cannot see every typo (measured 2026-10-13:
        # "normilazation", "ingestoin"); the model proposes and the same
        # strict-improvement gate decides. A failed call leaves the literal
        # question standing.
        reading = llm_second_reading(
            index, question, passages[0]["score"],
            generate_fn=generate_fn, word_map=word_map,
        )
    if reading is not None:
        context["reading"] = reading
        context["asked"] = reading["reading"]
        present = any(
            hit["chunk_id"] == reading["chunk"]["chunk_id"] for hit in passages
        )
        if not present:
            passages = [reading["chunk"]] + passages[:-1]
    asked = context["asked"]
    # Fusion pays one embed plus a full cosine pass. The lexical channel joins
    # only when the question carries a rare book word, the trigger the boost
    # used; other asks do not pay.
    if rare(asked, word_map):
        passages = fuse(index, asked, passages, word_map)
    # Caption seeding runs last: its measured effect is which chunk leads, and
    # fusion would otherwise be free to demote that lead.
    context["passages"] = caption_seed(index, asked, passages)
    return context


def ask(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
        canonical=True):
    generate_fn = generate_fn or ollama_generate
    asked_form = canonical_query(question) if canonical else question
    context = retrieval_context(index, asked_form, search_fn, generate_fn)
    passages = context["passages"]
    if not passages:
        return _refusal([])
    completion = generate_fn(SYSTEM, user_message(context["asked"], passages), model)
    anchors = anchor_words(asked_form, context["word_map"])
    body = parse_completion(
        completion, passages, index.get("figures") or [], anchors
    )
    if asked_form != question and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nAsked as: "{asked_form}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'
    return body


def respond(index, question, generate_fn=None, search_fn=None, model=ANSWER_MODEL,
            canonical=True):
    """Free-generation answer from the retrieved passages.

    No quote enforcement: the model writes, its [Ch. n] tags become the
    citations, and quotation marks the passages cannot back are stripped
    (see parse_answered). Groundedness is measured, not enforced. A question
    that asks for simple words routes through the plain register
    (`_plain_body`): the draft selects evidence sentences and each is
    rewritten one-in-one-out, so nothing is written from scratch. A bare
    topic phrase is asked as its question first (canonical_query).
    """
    generate_fn = generate_fn or ollama_generate
    asked_form = canonical_query(question) if canonical else question
    context = retrieval_context(index, asked_form, search_fn, generate_fn)
    passages = context["passages"]
    if not passages:
        return _refusal([])
    if simple_words(asked_form):
        body = _plain_body(index, context, generate_fn, model)
    else:
        completion = generate_fn(
            SYSTEM_ANSWER, answer_user_message(context["asked"], passages), model
        )
        body = parse_answered(completion, passages, index.get("figures") or [])
    if asked_form != question and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nAsked as: "{asked_form}"'
    if context["reading"] is not None and not body["refused"]:
        body["answer"] = f'{body["answer"]}\nRead as: "{context["asked"]}"'
    return body


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
    return (text or "").strip().split("\n", 1)[0].strip() == REFUSAL


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


def _tokens(text):
    """Word set for overlap scoring. Very short words carry little meaning."""
    return {word for word in _punctuation_plain(text).split() if len(word) > 2}


def _original_case(span, text):
    """The span as it is written in the passage, case and all."""
    flat = re.sub(r"\s+", " ", text or "")
    match = re.search(re.escape(span), flat, re.I)
    return match.group(0) if match else span


def _sentence_claims(text):
    """(claim, chapters) for every sentence carrying [Ch. tags.

    Tags are masked before the sentence split: "Ch." holds a period and would
    otherwise end a sentence inside the tag. The mask clears periods the
    captured text itself can hold — a two-chapter tag ("[Ch. 2, Ch. 7]")
    carries a second "Ch.", and a split inside the mask drops the claim
    entirely (measured 2026-10-13: the endpoint answer lost all citations).
    Text accumulates until a tag arrives, so a tag at the start of the next
    line still cites the sentence before it, and a tags-only fragment merges
    into the previous claim.
    """
    masked = TAG_PATTERN.sub(
        lambda m: "\x01" + re.sub(r"[.!?]", " ", m.group(1)) + "\x02", text
    )
    claims = []
    pending = ""
    for part in re.split(r"(?<=[.!?])\s+", masked):
        segments = []
        cursor = 0
        for match in re.finditer(r"\x01([^\x02]*)\x02", part):
            segments.append(("text", part[cursor:match.start()]))
            segments.append(("tag", match.group(1)))
            cursor = match.end()
        segments.append(("text", part[cursor:]))
        for kind, value in segments:
            if kind == "text":
                pending = (pending + " " + value).strip()
                continue
            chapters = re.findall(r"\d+", value)
            claim = re.sub(r"\s+", " ", pending).strip()
            if claim:
                claims.append([claim, chapters])
                pending = ""
            elif claims:
                claims[-1][1].extend(chapters)
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
    for sentence in _sentences(text):
        sentence_tokens = _tokens(sentence)
        if not sentence_tokens:
            continue
        overlap = len(tokens & sentence_tokens) / len(tokens) if tokens else 0.0
        holds = bool(span) and _fold(span) in _fold(sentence)
        if (overlap, holds) > best_key:
            best, best_key = sentence, (overlap, holds)
    if best:
        return _without_heading(best, hit)
    if span:
        return _original_case(span, text)
    return _without_heading(re.sub(r"\s+", " ", text).strip(), hit)


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
        citations.append({
            "chunk_id": hit["chunk_id"],
            "chapter": str(hit["chapter"]),
            "quote": _evidence_quote(claim, hit),
        })
    cited = {item["chunk_id"] for item in citations}
    named = [hit for hit in passages if hit["chunk_id"] in cited]
    return {
        "answer": text,
        "citations": citations,
        "figures": figures_for(named, figures or []),
        "refused": False,
    }


def explain(index, selection, generate_fn=None, search_fn=None, model=ANSWER_MODEL):
    """The highlight is the question. The neighborhood is the passages."""
    if not (selection or "").strip():
        raise ValueError("missing selection")
    return ask(index, selection.strip(), generate_fn, search_fn, model,
               canonical=False)


# A footnote marker glued to the citing line ("Maxime Beauchemin4") has no
# sentence-ending punctuation, so whitespace collapse runs the attribution
# into the next sentence. The split view only: the chunk text is untouched.
FOOTNOTE_GLUE = re.compile(r"\b[A-Z][a-z]{2,}(\d{1,3})(?=\s+[A-Z][a-z])")


def _sentences(text):
    raw = (text or "").strip()
    lines = raw.splitlines()
    if len(lines) > 1 and not lines[0].strip().endswith((".", "?", "!")):
        raw = "\n".join(lines[1:])
    flat = re.sub(r"\s+", " ", raw).strip()
    parts = []
    for run in re.split(r"(?<=[.!?])\s+", flat):
        cursor = 0
        for match in FOOTNOTE_GLUE.finditer(run):
            parts.append(run[cursor:match.end()])
            cursor = match.end()
        parts.append(run[cursor:])
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
