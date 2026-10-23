import re

from engine.figures import figures_for
from engine.answering.sentences import (
    split_sentences,
    token_word_pattern,
    WHITESPACE_RE,
)
from engine.answering.textrules import (
    PARAGRAPH_CAP,
    PRONOUNS_SET,
    REGARDING_PREFIX_RE,
    SPAN_MIN_CHARS,
)
from engine.answering.listshape import without_heading


SIDE_SPLIT = re.compile(r"[^a-z0-9]+")
SIDE_DROP = frozenset({
    "what", "is", "the", "difference", "between", "and", "vs", "versus",
    "how", "why", "who", "which", "are", "was", "were", "do", "does", "did",
    "can", "could", "should", "would", "a", "an", "with", "from", "than", "to",
    "against", "or",
})
COMPARISON_PATTERNS = (
    re.compile(r"\bdifference\s+between\s+(.+?)\s+and\s+(.+?)\s*[?.!]*$", re.I),
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+(?:stack\s+up\s+against|compare\s+(?:to|with|against)|compared\s+(?:to|with|against)|measure\s+up\s+(?:to|against)|differ\s+from)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    re.compile(
        r"\b(?:how\s+(?:does|do|can|is|are)\s+)?(.+?)\s+and\s+(.+?)\s+compare\s*[?.!]*$",
        re.I,
    ),
    re.compile(
        r"\b(?:compare|comparing|contrast|contrasting|distinguish(?:\s+between)?)\s+(.+?)\s+(?:and|with|to|from|vs\.?|versus)\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    re.compile(
        r"\b(?:is|are|was|were)\s+(.+?)\s+(?:better|worse|faster|slower|cheaper|simpler|more\s+\w+|less\s+\w+)\s+than\s+(.+?)\s*[?.!]*$",
        re.I,
    ),
    re.compile(r"\bwhat\s+sets\s+(.+?)\s+apart\s+from\s+(.+?)\s*[?.!]*$", re.I),
)
ONE_VERSUS = re.compile(r"\bvs\.?(?!\w)|\bversus\b", re.I)


def _clean_side(text):
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


def comparison_sides(*texts):
    candidates = [text.strip() for text in texts if text and text.strip()]
    pronouns = PRONOUNS_SET
    for text in candidates:
        prefix_subj = ""
        q_clean = (text or "").strip()
        m_reg = REGARDING_PREFIX_RE.match(q_clean)
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


def side_tokens(side):
    cleaned = _clean_side(side)
    tokens = []
    for token in SIDE_SPLIT.split((cleaned or "").lower()):
        if len(token) < 3 or token in SIDE_DROP:
            continue
        tokens.append(token)
    return tokens


def _side_covered(tokens, passages):
    if not tokens:
        return None
    patterns = [token_word_pattern(token) for token in tokens]
    for hit in passages:
        folded = f"{hit.get('heading') or ''} {hit.get('text') or ''}".lower()
        if all(pattern.search(folded) for pattern in patterns):
            return hit
    return None


def _covering_quote(tokens, hit):
    text = hit.get("text") or ""
    patterns = [token_word_pattern(token) for token in tokens]
    for sentence in split_sentences(text):
        if all(pattern.search(sentence.lower()) for pattern in patterns):
            return without_heading(sentence, hit)
    paragraph = WHITESPACE_RE.sub(" ", text).strip()
    if (
        len(paragraph) <= PARAGRAPH_CAP
        and len(paragraph) >= SPAN_MIN_CHARS
        and all(pattern.search(paragraph.lower()) for pattern in patterns)
    ):
        return without_heading(paragraph, hit)
    return ""


def half_covered(body, question, asked_form, passages, figures):
    sides = comparison_sides(question, asked_form)
    if sides is None:
        return body
    found = []
    for side in sides:
        tokens = side_tokens(side)
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
