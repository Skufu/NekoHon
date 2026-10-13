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
"""

import re

WH = re.compile(r"\b(what|which|when|where|who|whose|why|how)\b")
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
    "types", "kinds", "examples", "difference",
))
PRONOUNS = frozenset(("i", "me", "my", "mine", "you", "your", "we", "our", "us"))


def canonical_query(question):
    """The question the phrase means, or the phrase unchanged.

    Returns the original text (not stripped) when the trigger does not
    fire, so a caller can compare identity to know whether it did.
    """
    text = (question or "").strip()
    words = text.lower().split()
    if not words:
        return question or ""
    if "?" in text or text.endswith((".", "!")):
        return question
    folded = text.lower()
    if WH.search(folded):
        return question
    if words[0] in AUX or words[0] in OPENERS:
        return question
    if any(word in PRONOUNS for word in words):
        return question
    return f"What is {text}?"
