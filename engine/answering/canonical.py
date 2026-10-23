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
    return bool(DEICTIC_QUESTION_RE.match(q or ""))


def is_incomplete_stem(text):
    if is_deictic_question(text):
        return False
    cleaned = re.sub(r"[?!.,]", "", (text or "").lower()).strip()
    words = cleaned.split()
    if not words:
        return False
    return all(w in STEM_WORDS for w in words)


@functools.lru_cache(maxsize=512)
def canonical_query(question):
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
