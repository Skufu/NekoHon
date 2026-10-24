"""Fairness rules for the answer-model gates.

The rule: a citation passes when the passage it points at answers the
question. A pin is a note. These tests keep that rule from drifting back to
"the first citation must equal this one chunk", which measured agreement with
a 2026-10-12 pick rather than correctness (see the 2026-10-24 report).

Also checks that every pin in `battery-pins.json` actually carries the terms
authored for its question, and that the two pins replaced on 2026-10-24 really
do fail their own terms.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import fair_cite  # noqa: E402

PINS = ROOT / "artifacts" / "datasets" / "battery-pins.json"
INDEX = ROOT / "data" / "index.json"


def load_index():
    if not INDEX.is_file():
        return None
    return json.loads(INDEX.read_text(encoding="utf-8"))


class PinContentTest(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads(PINS.read_text(encoding="utf-8"))
        self.index = load_index()

    def _groups(self):
        for group in ("golden", "probes", "typos"):
            for item in self.pins[group]:
                yield group, item

    def test_every_golden_question_has_content_terms(self):
        for item in self.pins["golden"]:
            self.assertTrue(
                item.get("terms"),
                f"golden item needs terms or the gate is identity-only: {item['question']}",
            )

    def test_every_pin_carries_its_terms(self):
        if self.index is None:
            self.skipTest("index not on this machine (data/ is gitignored)")
        text_of = fair_cite.text_lookup(self.index)
        for group, item in self._groups():
            terms = item.get("terms") or []
            if not terms:
                continue
            missing = fair_cite.missing_terms(terms, text_of(item["pin"]))
            self.assertEqual(
                missing,
                [],
                f"{group} pin {item['pin']} does not carry {missing} for {item['question']!r}",
            )

    def test_replaced_pins_are_documented_and_were_wrong(self):
        if self.index is None:
            self.skipTest("index not on this machine (data/ is gitignored)")
        text_of = fair_cite.text_lookup(self.index)
        replaced = [item for _, item in self._groups() if item.get("replaced")]
        self.assertEqual(len(replaced), 2, "expected the two 2026-10-24 re-pins")
        for item in replaced:
            self.assertTrue(item.get("why"), f"{item['replaced']} needs a why")
            old_text = text_of(item["replaced"])
            self.assertNotEqual(
                fair_cite.missing_terms(item["terms"], old_text),
                [],
                f"{item['replaced']} satisfies its own terms; the replacement was not justified",
            )


class JudgeCitationTest(unittest.TestCase):
    def setUp(self):
        self.texts = {
            "a": "Storage is the cornerstone and underlies ingestion, transformation and serving.",
            "b": "The lifecycle has five stages: generation, storage, ingestion, transformation, serving.",
            "c": "Watermarks let a pipeline bound how long it waits for late events.",
        }
        self.text_of = lambda chunk_id: self.texts.get(chunk_id, "")

    def test_different_passage_that_answers_is_accepted(self):
        ok, detail = fair_cite.judge_citation(["b"], self.text_of, ["storage", "generation"])
        self.assertTrue(ok, detail)

    def test_passage_without_the_subject_is_rejected(self):
        ok, detail = fair_cite.judge_citation(["a"], self.text_of, ["storage", "generation"])
        self.assertFalse(ok)
        self.assertIn("generation", detail)

    def test_off_topic_passage_is_rejected(self):
        ok, _ = fair_cite.judge_citation(["c"], self.text_of, ["storage", "generation"])
        self.assertFalse(ok)

    def test_one_good_citation_among_many_is_enough(self):
        ok, detail = fair_cite.judge_citation(["c", "b"], self.text_of, ["storage", "generation"])
        self.assertTrue(ok, detail)

    def test_no_citations_fails(self):
        ok, _ = fair_cite.judge_citation([], self.text_of, ["storage"])
        self.assertFalse(ok)


class JudgeChapterTest(unittest.TestCase):
    def test_expected_chapter_passes(self):
        ok, _ = fair_cite.judge_chapter(["3"], 3, None, "", [])
        self.assertTrue(ok)

    def test_wrong_chapter_with_content_passes(self):
        ok, detail = fair_cite.judge_chapter(["7"], 3, None, "the data mesh has four principles", ["data mesh"])
        self.assertTrue(ok, detail)

    def test_wrong_chapter_without_content_fails(self):
        ok, _ = fair_cite.judge_chapter(["7"], 3, None, "something else entirely", ["data mesh"])
        self.assertFalse(ok)

    def test_no_terms_means_no_escape(self):
        ok, _ = fair_cite.judge_chapter(["7"], 3, None, "anything", [])
        self.assertFalse(ok)


class NoIdentityGateTest(unittest.TestCase):
    """Crude source guard against reintroducing identity-only gates."""

    def test_battery_does_not_compare_first_citation_to_a_chunk(self):
        source = (ROOT / "artifacts" / "harnesses" / "step2-battery.py").read_text(encoding="utf-8")
        self.assertNotIn("first != chunk", source)
        self.assertNotIn("first != pin", source)

    def test_hard_bench_does_not_require_the_gold_chunk(self):
        source = (ROOT / "artifacts" / "harnesses" / "hard-bench.py").read_text(encoding="utf-8")
        self.assertNotIn("does not include expected gold", source)


if __name__ == "__main__":
    unittest.main()
