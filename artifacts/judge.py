"""Cross-family LLM judge for the eval harness. Artifact, not engine.

Judged by `granite4.1:8b`, not by the answering model: a model judging its own
family's answers prefers them, and this box has a second family on disk. Two
jobs, both one-word verdicts at temperature 0:

- relevance: is one shown passage relevant to the question? The direct
  precision reading ("returned 5 passages, how many are actually relevant").
- key_fact: does the answer state the key fact, paraphrase allowed? Rescues
  regex misses in the eval's key_fact check.

The verdicts are UNVALIDATED against human labels until the eval set grows a
hand-labeled sample; count them, never treat them as truth. Set JUDGE_MODEL
to swap judges; a judge from the answerer's family (qwen) would be a
self-preference hazard and is not the default.
"""

import os
import re

import answer as A

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "granite4.1:8b")
PASSAGE_CHARS = 2000  # prompt-size guard, not a quality knob
ANSWER_CHARS = 2000

RELEVANCE_SYSTEM = (
    "You are a strict retrieval judge for a book question-answering system. "
    "You see one question and one passage from the book. Reply with exactly "
    "one word: relevant, if the passage contains information that helps "
    "answer the question; not_relevant, if it does not. No other words."
)
KEY_FACT_SYSTEM = (
    "You check a system answer against one key fact. Reply with exactly one "
    "word: states, if the answer states the key fact (paraphrase allowed); "
    "missing, if it does not. No other words."
)

# Ordered: the negative phrasings are checked before the bare positive word,
# so "not relevant" cannot match "relevant".
RELEVANCE_KEYS = [
    ("not_relevant", ["not relevant", "irrelevant", "no", "false"]),
    ("relevant", ["relevant", "yes", "true"]),
]
KEY_FACT_KEYS = [
    ("missing", ["missing", "not stated", "not mentioned", "no", "false"]),
    ("states", ["states", "yes", "true"]),
]


def _one_word(system, user, keys, model=JUDGE_MODEL, timeout=60):
    text = A.ollama_generate(system, user, model, timeout=timeout)
    normalized = re.sub(r"[^a-z]+", " ", text.strip().lower())
    for label, phrases in keys:
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                return label
    return "judge_error"


def judge_relevance(question, passage, model=JUDGE_MODEL, timeout=60):
    user = f"Question: {question}\n\nPassage:\n{passage[:PASSAGE_CHARS]}"
    return _one_word(RELEVANCE_SYSTEM, user, RELEVANCE_KEYS, model, timeout)


def judge_key_fact(question, key_fact, answer, model=JUDGE_MODEL, timeout=60):
    user = (
        f"Question: {question}\nKey fact: {key_fact}\n\n"
        f"System answer:\n{answer[:ANSWER_CHARS]}"
    )
    return _one_word(KEY_FACT_SYSTEM, user, KEY_FACT_KEYS, model, timeout)
