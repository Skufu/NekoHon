"""The form canonicalizer: a bare phrase asks the question it means.

Measured 2026-10-13 (`probe-class-variance-2026-10-13.*`): a bare topic
label reaches the model untyped, and the model answers labels with surveys
— the label pulled neighbor passages and three figures, while its question
form stayed on the one naming chunk. The prefix applies before retrieval
and the prompt, so both see the same string; a prefix that reaches only the
prompt refused the ask-mode question in the same probe.

Structural only: no "?", no wh-word anywhere, first token not an auxiliary
or an opener/imperative/list marker, no pronoun anywhere. Those are closed
English classes, not topic lists; a question the trigger does not recognize
passes through byte-for-byte. The rewrite is visible in the answer
(`Asked as:`), the readings-repair precedent.

Measured 2026-10-15 (owner-rated row 27): a comparison label the owner wrote
as `Monolith Versus Modular` was asked as `What is Monolith Versus Modular?`
— a definition, when the reader wanted the comparison. So a text with
exactly one comparator (vs / vs. / versus) is asked as `the difference
between X and Y`, before the bare-phrase rules; that also catches the
question-shaped form (`What is data science vs data engineering?`), which
the old order answered as a definition. Anything else the connector sits
in — two or more connectors, a sentence, an already-spelled-out
difference question — passes through byte-for-byte.
"""

import functools
import re

WH = re.compile(r"\b(what|which|when|where|who|whose|why|how)\b")
COMPARATOR = re.compile(r"\b(?:vs\.?(?!\w)|versus\b)", re.IGNORECASE)
COMPARED_TO = re.compile(r"\b(?:compared\s+(?:to|with|against))\b", re.IGNORECASE)
COMPARE_START = re.compile(
    r"^compare\s+(.+?)\s+(?:and|with|to)\s+(.+?)$", re.IGNORECASE
)
DISTINGUISH_START = re.compile(
    r"^distinguish\s+(?:between\s+)?(.+?)\s+(?:and|from)\s+(.+?)$", re.IGNORECASE
)
SETS_APART = re.compile(
    r"^(?:what\s+)?sets\s+(.+?)\s+apart\s+from\s+(.+?)$", re.IGNORECASE
)
DIFFER_FROM = re.compile(
    r"^(?:how\s+(?:does|do)\s+)?(.+?)\s+differs?\s+from\s+(.+?)$", re.IGNORECASE
)
LEAD_WHAT = re.compile(r"^what(?:\s+is|'s)\s+", re.IGNORECASE)
AUX = frozenset((
    "is", "are", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "has", "have", "had",
))
# Openers, imperatives, and list markers already carry a shape the model
# acts on; prefixing would mangle them ("explain …", "types of …",
# "hey can you tell me about …").
OPENERS = frozenset((
    "hey", "hi", "hello", "please", "pls", "tell", "show", "give",
    "explain", "describe", "define", "compare", "contrast", "list",
    "types", "kinds", "examples", "difference", "distinguish",
))
PRONOUNS = frozenset(("i", "me", "my", "mine", "you", "your", "we", "our", "us"))
STEM_WORDS = frozenset((
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "should",
    "would", "will", "the", "a", "an", "of", "in", "to", "for", "on", "about",
    "this", "that", "these", "those", "they", "it",
))

DEICTIC_QUESTION_RE = re.compile(
    r"^\s*(?:what|why|how|who|where|when)\s+(?:is|are|was|were|does|do|did|can|should|would|will)\s+(?:this|that|it|these|those|they)(?:\s+(?:mean|work|matter|do|for|about|refer\s+to|important))?\s*\??\s*$",
    re.IGNORECASE,
)


def is_deictic_question(q):
    """True when q is a self-contained deictic question (e.g. 'what is this',
    'what does this mean', 'how does this work', 'why is this')."""
    return bool(DEICTIC_QUESTION_RE.match(q or ""))


def is_incomplete_stem(text):
    """True when text is an incomplete question prefix composed entirely of
    wh-words, auxiliaries, articles, and prepositions."""
    if is_deictic_question(text):
        return False
    cleaned = re.sub(r"[?!.,]", "", (text or "").lower()).strip()
    words = cleaned.split()
    if not words:
        return False
    return all(w in STEM_WORDS for w in words)


@functools.lru_cache(maxsize=512)
def canonical_query(question):
    """The question the phrase means, or the phrase unchanged.

    Returns the original text (not stripped) when the trigger does not
    fire, so a caller can compare identity to know whether it did.
    """
    text = (question or "").strip()
    words = text.lower().split()
    if not words:
        return question or ""
    if text.endswith((".", "!")):
        return question
    if (COMPARATOR.search(text)
            or COMPARED_TO.search(text)
            or COMPARE_START.match(text)
            or DISTINGUISH_START.match(text)
            or SETS_APART.match(text)
            or DIFFER_FROM.match(text)):
        return _comparison_query(question, text)
    if "?" in text:
        return question
    folded = text.lower()
    if WH.search(folded):
        return question
    if words[0] in AUX or words[0] in OPENERS:
        return question
    if any(word in PRONOUNS for word in words):
        return question
    return f"What is {text}?"


def _comparison_query(question, text):
    """Exactly one comparator: ask the comparison, or pass through.

    Fires for the bare label (`X versus Y`, `X compared to Y`, `compare X with Y`)
    and the definition-shaped question (`What is X versus Y?`, whose `?` and wh-word
    head the caller would otherwise return on). Everything else keeps its shape:
    two comparators, a sentence the connector merely appears in, a comparison
    already spelled out with `difference between`, or a dangling side.
    """
    body = text
    if text.endswith("?"):
        body = text[:-1].rstrip()
        if not body or "?" in body:
            return question
    if "?" in body or "difference between" in body.lower():
        return question

    core = LEAD_WHAT.sub("", body, count=1).strip()
    m_compare = COMPARE_START.match(core)
    if m_compare:
        left, right = m_compare.group(1).strip(), m_compare.group(2).strip()
        if left and right and not any(w in PRONOUNS for w in left.lower().split()):
            return f"What is the difference between {left} and {right}?"

    m_distinguish = DISTINGUISH_START.match(core)
    if m_distinguish:
        left, right = m_distinguish.group(1).strip(), m_distinguish.group(2).strip()
        if left and right and not any(w in PRONOUNS for w in left.lower().split()):
            return f"What is the difference between {left} and {right}?"

    m_sets = SETS_APART.match(core)
    if m_sets:
        left, right = m_sets.group(1).strip(), m_sets.group(2).strip()
        if left and right and not any(w in PRONOUNS for w in left.lower().split()):
            return f"What is the difference between {left} and {right}?"

    m_differ = DIFFER_FROM.match(core)
    if m_differ:
        left, right = m_differ.group(1).strip(), m_differ.group(2).strip()
        if left and right and not any(w in PRONOUNS for w in left.lower().split()):
            return f"What is the difference between {left} and {right}?"

    if len(COMPARED_TO.findall(core)) == 1:
        parts = COMPARED_TO.split(core, maxsplit=1)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            heads = left.lower().split()
            if (left and right and not (heads and heads[0] in AUX)
                    and not any(w in PRONOUNS for w in heads)):
                return f"What is the difference between {left} and {right}?"

    if len(COMPARATOR.findall(core)) != 1:
        return question
    heads = core.lower().split()
    if (not heads or heads[0] in AUX or heads[0] in OPENERS
            or WH.search(core.lower())
            or any(word in PRONOUNS for word in heads)):
        return question
    left, right = (part.strip() for part in COMPARATOR.split(core, maxsplit=1))
    if not left or not right:
        return question
    return f"What is the difference between {left} and {right}?"
