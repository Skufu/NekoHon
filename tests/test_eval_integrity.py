"""Regressions for eval verdicts that used to accept fabricated evidence."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts/harnesses"))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "artifacts/harnesses" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FAIR = load("fair-eval")
HARD = load("hard-bench")


class CitationIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.chunks = {
            "gold": {"chunk_id": "gold", "chapter": "1", "text": "A buffer temporarily holds records before writing."},
            "wrong": {"chunk_id": "wrong", "chapter": "1", "text": "A disk stores bytes persistently."},
        }
        self.item = {"id": "fixture", "category": "definition", "expect": "answer", "question": "What is a buffer?", "gold_chunks": ["gold"], "key_facts": ["buffer"]}
        self.result = {"refused": False, "answer": '[Ch. 1] "A buffer temporarily holds records before writing."\nA buffer keeps records briefly.', "citations": [{"chunk_id": "gold", "chapter": "1", "quote": self.chunks["gold"]["text"]}]}

    def test_wrong_chunk_cannot_borrow_gold_quote(self):
        self.result["citations"][0]["chunk_id"] = "wrong"
        self.assertFalse(FAIR.grade_fair(self.item, self.result, chunk_table=self.chunks)["passed"])

    def test_unknown_chunk_cannot_borrow_gold_quote(self):
        self.result["citations"][0]["chunk_id"] = "does-not-exist"
        self.assertFalse(FAIR.grade_fair(self.item, self.result, chunk_table=self.chunks)["passed"])

    def test_one_valid_quote_cannot_hide_a_second_fabricated_quote(self):
        self.result["citations"].append({"chunk_id": "wrong", "chapter": "1", "quote": "Fabricated quote."})
        self.assertFalse(FAIR.grade_fair(self.item, self.result, chunk_table=self.chunks)["passed"])

    def test_short_correct_definition_still_passes(self):
        self.assertTrue(FAIR.grade_fair(self.item, self.result, chunk_table=self.chunks)["passed"])

    def test_lying_chapter_tag_cannot_override_cited_chunk(self):
        self.chunks["gold"]["chapter"] = "2"
        self.assertFalse(FAIR.grade_fair(self.item, self.result, chunk_table=self.chunks)["passed"])

    def test_zero_exercised_negative_controls_cannot_validate_a_benchmark(self):
        controls, valid = HARD.run_controls([], [], {}, lambda item: {}, lambda item: ({}, 0))
        self.assertFalse(valid)
        self.assertTrue(all(row["answer_items_total"] == 0 for row in controls.values()))

    def test_hard_bench_rejects_unknown_citation_even_when_gloss_matches(self):
        self.item["category"] = "multi_turn"
        self.item["key_fact"] = "buffer"
        self.result["citations"][0]["chunk_id"] = "missing"
        grade = HARD.grade_item(self.item, self.result, self.chunks, {k: c["text"] for k, c in self.chunks.items()})
        self.assertFalse(grade["passed"])
        self.assertTrue(any("unknown" in reason for reason in grade["reasons"]))


if __name__ == "__main__":
    unittest.main()
