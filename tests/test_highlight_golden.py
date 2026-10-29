"""Pins the highlight golden set. Reads jsonl. No builder, no Ollama."""

import importlib.util
import json
import re
import unittest
from pathlib import Path

from answer import highlight_query, user_message
from prompt import SYSTEM

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





def load_probe_highlight():
    spec = importlib.util.spec_from_file_location(
        "probe_highlight",
        ROOT / "artifacts" / "probes" / "probe-highlight-2026-10-16.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HighlightScorerStrictTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe_highlight()
        cls.pin_text = (
            "Plenty of great modular services are available to choose from in "
            "either case. The shifting reality of how companies adopt software "
            "is worth mentioning. Technology adoption within companies is becoming "
            "an organic, continuous process."
        )
        cls.selection = "great"

    def test_check_gloss_rejects_empty_and_trivial(self):
        for dummy in ("", "   ", "x", "X"):
            ok, detail, _ = self.probe.check_gloss(dummy, self.selection, self.pin_text)
            self.assertFalse(ok, f"expected failure for dummy gloss {dummy!r}, got detail: {detail}")

    def test_check_gloss_rejects_repeating_selection(self):
        for repeat in ("great", "Great", "GREAT", "great."):
            ok, detail, _ = self.probe.check_gloss(repeat, self.selection, self.pin_text)
            self.assertFalse(ok, f"expected failure when gloss repeats selection: {repeat!r}")

    def test_check_gloss_rejects_ungrounded_lorem_ipsum(self):
        lorem = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor."
        ok, detail, metrics = self.probe.check_gloss(lorem, self.selection, self.pin_text)
        self.assertFalse(ok, f"expected ungrounded failure for lorem ipsum, got: {detail}")
        self.assertLess(metrics["grounded_ratio"], 0.5)

    def test_check_gloss_accepts_faithful_gloss(self):
        faithful = "Plenty of great modular services are available to choose from in either case."
        ok, detail, metrics = self.probe.check_gloss(faithful, self.selection, self.pin_text)
        self.assertTrue(ok, f"expected faithful gloss to pass, got: {detail}")
        self.assertGreaterEqual(metrics["grounded_ratio"], 0.5)

    def test_score_strict_proves_dummy_generator_fails_while_faithful_passes(self):
        quote = "Plenty of great modular services are available to choose from in either case."
        dummy_body = {
            "_pin": "ch04-051",
            "answer": f'[Ch. 4] "{quote}"\nx',
            "citations": [{"chunk_id": "ch04-051", "quote": quote}],
            "refused": False,
        }
        # Legacy score: citation and quote pass, so legacy scorer marks it ok (defect)
        legacy_res = self.probe.score(dummy_body, self.pin_text, self.selection)
        self.assertTrue(
            not legacy_res["refused"]
            and legacy_res["pin_cited"]
            and legacy_res["quote_verbatim_in_pin"]
            and legacy_res["word_in_quoted_span"],
            "Legacy scorer defect: passes dummy generator because gloss is never verified",
        )

        # Stricter opt-in score: dummy gloss must FAIL
        strict_dummy_res = self.probe.score_strict(dummy_body, self.pin_text, self.selection)
        self.assertFalse(strict_dummy_res["passed"], "Dummy gloss 'x' must fail under strict scoring")
        self.assertFalse(strict_dummy_res["gloss_valid"])

        # Faithful gloss must PASS
        faithful_body = {
            "_pin": "ch04-051",
            "answer": f'[Ch. 4] "{quote}"\n{quote}',
            "citations": [{"chunk_id": "ch04-051", "quote": quote}],
            "refused": False,
        }
        strict_faithful_res = self.probe.score_strict(faithful_body, self.pin_text, self.selection)
        self.assertTrue(strict_faithful_res["passed"], "Faithful gloss must pass under strict scoring")
        self.assertTrue(strict_faithful_res["gloss_valid"])


if __name__ == "__main__":
    unittest.main()
