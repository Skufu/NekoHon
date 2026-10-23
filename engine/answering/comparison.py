import re

from engine.figures import figures_for
from engine.answering.shared import (
    PARAGRAPH_CAP,
    SPAN_MIN_CHARS,
    _PRONOUNS_SET,
    _REGARDING_PREFIX_RE,
    _WHITESPACE_RE,
    _sentences,
    _token_word_pattern,
    tokens,
)
from engine.answering.listshape import _without_heading


# Digits stay: a version token is one side of a comparison, and splitting on
# letters alone would fold both numbered sides into the same stem.
SIDE_SPLIT = re.compile(r"[^a-z0-9]+")
SIDE_DROP = frozenset({
    "what", "is", "the", "difference", "between", "and", "vs", "versus",
    "how", "why", "who", "which", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "a", "an", "with", "from", "than", "to",
    "against", "or",
})
COMPARISON_PATTERNS = (
    # 1) difference between X and Y
    re.compile(r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)\s*[?.!]*$", re.I),
    # 2) how does X stack up against / compare to / compared to / measure up to / differ from Y
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+(?:stack\s+up\s+against|compare\s+(?:to|with|against)|compared\s+(?:to|with|against)|measure\s+up\s+(?:to|against)|differ\s+from)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 2b) how do X and Y compare
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+and\s+(.+?)\s+compare\s*[?.!]*$",
        re.I,
    ),
    # 3) compare / contrast / distinguish X and/with/to/from/vs Y
    re.compile(
        r"\b(?:compare|comparing|contrast|contrasting|distinguish(?:\s+between)?)\s+(.+?)\s+(?:and|with|to|from|vs\.?|versus)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 4) is/are/was/were X better/worse/faster/slower/cheaper/simpler/more .../less ... than Y
    re.compile(
        r"\b(?:is|are|was|were)\s+(.+?)\s+(?:better|worse|faster|slower|cheaper|simpler|more\s+\w+|less\s+\w+)\s+than\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    # 5) what sets X apart from Y
    re.compile(r"\bwhat\s+sets\s+(.+?)\s+apart\s+from\s+(.+?)\s*[?.!]*$", re.I),
)
ONE_VERSUS = re.compile(r"\bvs\.?(?!\w)|\bversus\b", re.I)


def _clean_side(text):
    """Strip question fillers, auxiliaries, and articles from a comparison side."""
    text = (text or "").strip(" ?.!\"'")
    text = re.sub(
        r"^(?:what\s+is|what\s+are|how\s+does|how\s+do|how\s+is|how\s+are|why\s+is|why\s+does)\s+",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^(?:is|are|was|were|do|does|did|can|could|should|would)\s+",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.I)
    return text.strip(" ?.!\"'")


def _comparison_sides(*texts):
    """(left, right) raw sides of a comparison, or None.

    Matches difference-between, comparison predicates, compare/contrast,
    comparative adjectives, what-sets-apart, or exactly one vs/versus.
    Either the original question or its canonical rewrite qualifies.
    """
    candidates = [text.strip() for text in texts if text and text.strip()]
    pronouns = _PRONOUNS_SET
    for text in candidates:
        prefix_subj = ""
        q_clean = (text or "").strip()
        m_reg = _REGARDING_PREFIX_RE.match(q_clean)
        if m_reg:
            prefix_subj = m_reg.group(1).strip()
            q_clean = m_reg.group(2).strip()

        for pat in COMPARISON_PATTERNS:
            match = pat.search(q_clean)
            if match:
                left = _clean_side(match.group(1))
                right = _clean_side(match.group(2))
                if left and left.lower() in pronouns:
                    left = prefix_subj if prefix_subj else None
                if right and right.lower() in pronouns:
                    right = prefix_subj if prefix_subj else None
                if not left or not right:
                    continue
                if "regarding " in left.lower() or "regarding " in right.lower():
                    continue
                if "how does " in left.lower() or "how does " in right.lower():
                    continue
                if left.lower() in pronouns or right.lower() in pronouns:
                    continue
                return left, right

        hits = list(ONE_VERSUS.finditer(q_clean))
        if len(hits) == 1:
            hit = hits[0]
            left = _clean_side(q_clean[:hit.start()])
            right = _clean_side(q_clean[hit.end():])
            if left and left.lower() in pronouns:
                left = prefix_subj if prefix_subj else None
            if right and right.lower() in pronouns:
                right = prefix_subj if prefix_subj else None
            if not left or not right:
                continue
            if "regarding " in left.lower() or "regarding " in right.lower():
                continue
            if "how does " in left.lower() or "how does " in right.lower():
                continue
            if left.lower() in pronouns or right.lower() in pronouns:
                continue
            return left, right

    return None


def _side_tokens(side):
    """Content tokens of one side. Closed function words and short tokens drop."""
    cleaned = _clean_side(side)
    tokens = []
    for token in SIDE_SPLIT.split((cleaned or "").lower()):
        if len(token) < 3 or token in SIDE_DROP:
            continue
        tokens.append(token)
    return tokens


def _side_covered(tokens, passages):
    """The shown passage holding every token as a whole word, or None."""
    if not tokens:
        return None
    patterns = [_token_word_pattern(token) for token in tokens]
    for hit in passages:
        folded = f"{hit.get('heading') or ''} {hit.get('text') or ''}".lower()
        if all(pattern.search(folded) for pattern in patterns):
            return hit
    return None


def _covering_quote(tokens, hit):
    """A verbatim sentence naming the covered side, else its paragraph.

    Nothing under the quote floor is invented into a sentence. Empty when the
    passage has no quotable span that names the side.
    """
    text = hit.get("text") or ""
    patterns = [_token_word_pattern(token) for token in tokens]
    for sentence in _sentences(text):
        if all(pattern.search(sentence.lower()) for pattern in patterns):
            return _without_heading(sentence, hit)
    paragraph = _WHITESPACE_RE.sub(" ", text).strip()
    if (
        len(paragraph) <= PARAGRAPH_CAP
        and len(paragraph) >= SPAN_MIN_CHARS
        and all(pattern.search(paragraph.lower()) for pattern in patterns)
    ):
        return _without_heading(paragraph, hit)
    return ""


def _half_covered(body, question, asked_form, passages, figures):
    """Answer the covered side of a comparison when only one side is in the passages.

    Fires only when exactly one side is in the shown passages and a verbatim
    span can be quoted. The other side is named in a gloss, never quoted and
    never given attributes the passages do not contain.
    """
    sides = _comparison_sides(question, asked_form)
    if sides is None:
        return body
    found = []
    for side in sides:
        tokens = _side_tokens(side)
        found.append((side, tokens, _side_covered(tokens, passages)))
    covered = [item for item in found if item[2] is not None]
    missing = [item for item in found if item[2] is None]
    if len(covered) != 1 or len(missing) != 1:
        return body
    missing_name = missing[0][0].strip()
    if missing_name.lower().startswith("regarding") or missing_name.lower().startswith("in "):
        return body
    if (not body.get("refused")
            and missing_name.lower() in body.get("answer", "").lower()
            and re.search(r"\b(not\s+mention|does\s+not|do\s+not|absent)\b", body.get("answer", ""), re.I)):
        return body
    side, tokens, hit = covered[0]
    quote = _covering_quote(tokens, hit)
    if not quote:
        return body
    chapter = str(hit["chapter"])
    gloss = f"The passages do not mention {missing_name}."
    return {
        "answer": f'[Ch. {chapter}] "{quote}"\n{gloss}',
        "citations": [{
            "chunk_id": hit["chunk_id"],
            "chapter": chapter,
            "quote": quote,
        }],
        "figures": figures_for([hit], figures or []),
        "refused": False,
    }
