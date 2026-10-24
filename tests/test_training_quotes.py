"""Every in-book quote in a training row must exist verbatim in the book.

Why this exists: on 2026-10-24 an old follow-up dataset turned out to have 10 of
15 quotes that exist nowhere in the three books. One of them attached a rewritten
ACID definition to an OLTP passage. The engine retrieved the right chunk; the
dataset had never been checked against the book.

Scope, stated because a previous unscoped count was wrong (88 "bad" quotes that
were other-domain rows and figure captions):

- only rows whose first `chunk_id` belongs to one of the three indexed books
  (`ch*`, `app*`, `text*`, `chapter-*`) are checked;
- figure captions and their referencing paragraphs count as book text;
- refusals (`Not in this book.`) and rows without a `messages` array are skipped.

`data/` is gitignored; the test skips when the corpus or index is absent.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import answer as A  # noqa: E402
from retrieve import load_index  # noqa: E402

DATA = ROOT / "data" / "finetune"
INDEXES = [
    ROOT / "data" / "index.json",
    ROOT / "data" / "index.quantization.json",
    ROOT / "data" / "index.ddia.json",
]
IN_BOOK = re.compile(r"^(ch\d|app\d|text\d|chapter-)")
QUOTE = re.compile(r'\[Ch\.\s*[^\]]+\]\s*["“](.+?)["”]', re.S)
REFUSAL = "Not in this book."


def book_texts():
    texts = []
    for path in INDEXES:
        if not path.is_file():
            continue
        index = load_index(path)
        for chunk in index.get("chunks", []):
            texts.append(chunk.get("text") or "")
        for figure in index.get("figures", []):
            texts.append(
                (figure.get("caption") or "") + " " + (figure.get("referencing_paragraph") or "")
            )
    return texts


def folded_books(texts):
    """Pre-fold every book text the two ways `_quote_in_passage` compares.

    Calling `_quote_in_passage` per quote re-normalizes 3,000 texts every time
    (100 s for the corpus). This does it once.
    """
    folded, punct = [], []
    for text in texts:
        stripped = A._strip_figure_refs(text)
        folded.append(re.sub(r"\s+", " ", stripped).lower())
        punct.append(A._punctuation_plain(stripped))
    return folded, punct


def quote_in_book(folded, punct, quote):
    stripped = A._strip_figure_refs(quote)
    if any(re.sub(r"\s+", " ", stripped).lower() in text for text in folded):
        return True
    punctuation_plain = A._punctuation_plain(stripped)
    return any(punctuation_plain in text for text in punct)


class TrainingQuoteTest(unittest.TestCase):
    def test_every_in_book_quote_is_verbatim(self):
        if not DATA.is_dir():
            self.skipTest("training data not on this machine (data/ is gitignored)")
        texts = book_texts()
        if not texts:
            self.skipTest("no index to check against")
        folded, punct = folded_books(texts)

        failures = []
        checked = 0
        for path in sorted(DATA.glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    messages = row.get("messages")
                    if not isinstance(messages, list):
                        continue
                    user = next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")
                    assistant = next(
                        (m.get("content") or "" for m in messages if m.get("role") == "assistant"), ""
                    ).strip()
                    if not assistant:
                        # Prompt-only files (seed sets) carry no target to check.
                        continue
                    if assistant == REFUSAL:
                        continue
                    chunk = re.search(r"chunk_id=([a-z0-9-]+)", user)
                    if not chunk or not IN_BOOK.match(chunk.group(1)):
                        continue
                    match = QUOTE.match(assistant)
                    if not match:
                        failures.append((path.name, lineno, "target has no quote line"))
                        continue
                    checked += 1
                    if not quote_in_book(folded, punct, match.group(1)):
                        failures.append((path.name, lineno, match.group(1)[:70]))

        self.assertGreater(checked, 0, "no in-book quotes found; check the glob")
        self.assertEqual(
            failures[:10],
            [],
            f"{len(failures)} in-book quote(s) are not verbatim; first 10: {failures[:10]}",
        )


if __name__ == "__main__":
    unittest.main()
