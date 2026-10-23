import json
import re
import unittest
from pathlib import Path

from engine.answering.answer import highlight_query, user_message
from engine.answering.prompt import SYSTEM

ROOT = Path(__file__).resolve().parent.parent
HELDOUT = ROOT / "artifacts" / "datasets" / "highlight-golden-2026-10-16.jsonl"
TRAIN = ROOT / "artifacts" / "datasets" / "highlight-train-2026-10-16.jsonl"
INDEX = ROOT / "data" / "index.json"
SEALED = ROOT / "artifacts" / "datasets" / "sealed-forms.json"
SOURCE = "highlight-golden-2026-10-16"
QUOTE_LINE = re.compile(r'^\[Ch\. (.+)\] "(.*)"$')
CHUNK_ID = re.compile(r"chunk_id=(\S+)")
MIN_QUOTE = 40


def load_jsonl(path):
    if not path.is_file():
        raise AssertionError(f"missing {path}")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def folded(text):
    return " ".join((text or "").split())


def row_id(meta):
    return f"{meta.get('split')}:{meta.get('chunk_id')}:{meta.get('selection')}"


def pin_prefix(asked, chunk):
    built = user_message(
        asked,
        [
            {
                "chunk_id": chunk["chunk_id"],
                "chapter": chunk.get("chapter"),
                "heading": chunk.get("heading") or "",
                "text": chunk.get("text") or "",
            }
        ],
    )
    prefix, found, _rest = built.partition("\n\nCopy one sentence")
    if not found:
        raise AssertionError("user_message lost the format reminder")
    return prefix


class HighlightGoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.heldout = load_jsonl(HELDOUT)
        cls.train = load_jsonl(TRAIN)
        if not INDEX.is_file():
            raise AssertionError(f"missing {INDEX}")
        if not SEALED.is_file():
            raise AssertionError(f"missing {SEALED}")
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        cls.chunks = {chunk["chunk_id"]: chunk for chunk in index["chunks"]}
        sealed = json.loads(SEALED.read_text(encoding="utf-8"))
        cls.sealed_items = list(sealed["items"])

    def _rows(self):
        yield from (("heldout", row) for row in self.heldout)
        yield from (("train", row) for row in self.train)

    def test_heldout_has_24_rows(self):
        self.assertEqual(len(self.heldout), 24)

    def test_train_has_72_rows(self):
        self.assertEqual(len(self.train), 72)

    def test_every_row_meta(self):
        for split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            self.assertEqual(meta["split"], split, rid)
            self.assertEqual(meta["row_type"], "highlight", rid)
            self.assertEqual(meta["source"], SOURCE, rid)

    def test_asked_matches_highlight_query(self):
        for _split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            self.assertEqual(
                meta["asked"],
                highlight_query(meta["selection"], meta["heading"]),
                rid,
            )

    def test_messages_use_system_and_asked(self):
        for _split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            messages = row["messages"]
            self.assertEqual(messages[0]["content"], SYSTEM, rid)
            self.assertTrue(
                messages[1]["content"].startswith(f"Question: {meta['asked']}"),
                rid,
            )

    def test_pinned_chunk_is_first_passage(self):
        for _split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            user = row["messages"][1]["content"]
            ids = CHUNK_ID.findall(user)
            self.assertTrue(ids, rid)
            self.assertEqual(ids[0], meta["chunk_id"], rid)
            pin = self.chunks.get(meta["chunk_id"])
            self.assertIsNotNone(pin, rid)
            prefix = pin_prefix(meta["asked"], pin)
            self.assertTrue(user.startswith(prefix), rid)

    def test_assistant_is_quote_then_same_sentence(self):
        for _split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            lines = row["messages"][2]["content"].splitlines()
            self.assertEqual(len(lines), 2, rid)
            match = QUOTE_LINE.fullmatch(lines[0])
            self.assertIsNotNone(match, rid)
            sentence = match.group(2)
            self.assertEqual(lines[1], sentence, rid)

    def test_sentence_is_grounded_in_the_pinned_chunk(self):
        for _split, row in self._rows():
            meta = row["meta"]
            rid = row_id(meta)
            match = QUOTE_LINE.fullmatch(row["messages"][2]["content"].splitlines()[0])
            self.assertIsNotNone(match, rid)
            sentence = match.group(2)
            pin = self.chunks.get(meta["chunk_id"])
            self.assertIsNotNone(pin, rid)
            self.assertGreaterEqual(len(sentence), MIN_QUOTE, rid)
            self.assertIn(folded(sentence), folded(pin.get("text") or ""), rid)
            self.assertIsNotNone(
                re.search(rf"\b{re.escape(meta['selection'])}\b", sentence, re.I),
                rid,
            )

    def test_heldout_and_train_chunk_ids_are_disjoint(self):
        held = {row["meta"]["chunk_id"] for row in self.heldout}
        train = {row["meta"]["chunk_id"] for row in self.train}
        overlap = held & train
        self.assertFalse(overlap, sorted(overlap))

    def test_no_duplicate_chunk_and_selection(self):
        seen = {}
        for split, row in self._rows():
            key = (row["meta"]["chunk_id"], row["meta"]["selection"])
            rid = row_id(row["meta"])
            self.assertNotIn(key, seen, f"{rid} duplicates {seen.get(key)}")
            seen[key] = rid

    def test_asked_is_not_a_sealed_form(self):
        sealed = set(self.sealed_items)
        for _split, row in self._rows():
            meta = row["meta"]
            self.assertNotIn(meta["asked"], sealed, row_id(meta))


if __name__ == "__main__":
    unittest.main()
