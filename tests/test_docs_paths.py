"""Docs must name paths that exist.

Every committed repo path written as an inline code span in `AGENTS.md`,
`README.md`, `GLOSSARY.md`, `docs/*.md` or `docs/adr/*.md` must resolve from the
repo root. Only tokens that start with a known top-level directory and contain
a slash are checked, so routes (`/chunks`), commands, globs and placeholders
(`data/index.<book_id>.sqlite`) are out of scope by construction.

Runtime-only trees are skipped: `data/`, `books/` and `artifacts/runs/` are
gitignored, so their absence from a fresh clone is not a doc bug.

This cannot check prose. It checks the one thing that rots silently: a deleted
file still being cited as the place to look.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCS = [ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "GLOSSARY.md"]
DOCS += sorted((ROOT / "docs").glob("*.md"))
DOCS += sorted((ROOT / "docs" / "adr").glob("*.md"))

COMMITTED_TOPS = {
    "docs", "web", "tests", "scripts", "artifacts", "models", "window", ".agents",
}
RUNTIME_PREFIXES = ("data/", "books/", "artifacts/runs/")

SPAN = re.compile(r"`([^`\n]+)`")
NOT_A_PATH = re.compile(r"[<>{}*\s]")


def claimed_paths(text):
    for raw in SPAN.findall(text):
        token = raw.rstrip(".,;:)")
        if NOT_A_PATH.search(token) or "/" not in token:
            continue
        if token.split("/", 1)[0] not in COMMITTED_TOPS:
            continue
        if token.startswith(RUNTIME_PREFIXES):
            continue
        yield token


class DocsPathTests(unittest.TestCase):
    def test_docs_only_name_paths_that_exist(self):
        broken = []
        for doc in DOCS:
            if not doc.is_file():
                continue
            for token in claimed_paths(doc.read_text(encoding="utf-8")):
                if not (ROOT / token).exists():
                    broken.append(f"{doc.relative_to(ROOT)} -> {token}")
        self.assertEqual(broken, [], "docs cite missing paths:\n" + "\n".join(broken))

    def test_the_checker_finds_paths(self):
        self.assertGreater(len(list(claimed_paths(
            "see `docs/ARCHITECTURE.md` and `artifacts/README.md`"))), 1)


if __name__ == "__main__":
    unittest.main()
