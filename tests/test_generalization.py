"""Guard: the logic modules must not be fitted to one book. No Ollama.

A retrieval or answer module that names a chunk id, a figure id, or a book id
has stopped being a system and become a lookup table. Those literals belong in
tests, pins, and the battery. Docstrings are exempt: the repo records measured
evidence there, including chunk ids.

ingest.py is deliberately not guarded. Naming the book file and the book id is
its job.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGIC = (
    "engine/answering/answer.py",
    "engine/answering/context.py",
    "engine/answering/conversation.py",
    "engine/answering/explain.py",
    "engine/answering/freeanswer.py",
    "engine/answering/generate.py",
    "engine/answering/gloss.py",
    "engine/answering/quiz.py",
    "engine/answering/quoteask.py",
    "engine/answering/comparison.py",
    "engine/answering/listshape.py",
    "engine/answering/messages.py",
    "engine/answering/quotecheck.py",
    "engine/answering/sanitize.py",
    "engine/answering/shared.py",
    "engine/answering/canonical.py",
    "engine/retrieval/captions.py",
    "engine/figures.py",
    "engine/llm.py",
    "engine/retrieval/fusion.py",
    "engine/answering/intent.py",
    "engine/retrieval/keywords.py",
    "engine/retrieval/preprocess.py",
    "engine/answering/prompt.py",
    "engine/retrieval/readings.py",
    "engine/retrieval/retrieve.py",
)
FORBIDDEN = (
    (re.compile(r"\bch\d{2}-\d{3}\b"), "chunk id"),
    (re.compile(r"\bfigure-\d+-\d+\b"), "figure id"),
    (re.compile(r"\bfde\b"), "book id"),
)


def _docstrings(tree):
    """The id() of every Constant that is a module, class, or function docstring."""
    found = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def code_literals(source):
    """(text, line) for every string literal that is not a docstring."""
    tree = ast.parse(source)
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        yield node.value, node.lineno


class GeneralizationTests(unittest.TestCase):
    def test_logic_modules_carry_no_book_literals(self):
        for name in LOGIC:
            path = ROOT / name
            self.assertTrue(path.is_file(), name)
            for text, line in code_literals(path.read_text(encoding="utf-8")):
                for pattern, label in FORBIDDEN:
                    if pattern.search(text):
                        self.fail(
                            f"{name}:{line} holds a {label} in code, not a docstring: "
                            f"{text[:60]!r}"
                        )

    def test_the_guard_catches_a_planted_literal(self):
        source = 'CHUNK = "ch04-020"\nFIGURE = "figure-4-1"\nBOOK = "fde"\n'
        found = [text for text, _ in code_literals(source)]
        for text in found:
            self.assertTrue(
                any(pattern.search(text) for pattern, _ in FORBIDDEN), text
            )
        self.assertEqual(len(found), 3)

    def test_a_docstring_may_still_name_a_chunk(self):
        source = '"""Measured: ch04-020 holds the sentence."""\n\nVALUE = 1\n'
        self.assertEqual([text for text, _ in code_literals(source)], [])


if __name__ == "__main__":
    unittest.main()
