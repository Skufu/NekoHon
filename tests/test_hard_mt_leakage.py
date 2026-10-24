"""The hard multi-turn bench must stay hard and stay held out.

Two tripwires, same shape as `test_eval_leakage.py`:

1. the dataset matches its frozen sha256, so an edit is a deliberate act;
2. no bench question repeats a training-corpus question, exactly or nearly;
3. the fabricated names and years in the trap items appear in no book, so the
   refusal is the only correct answer.

The corpus and the indexes are gitignored; the hash check runs everywhere, the
rest skip on a machine without them.
"""

import difflib
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "artifacts" / "datasets"
BENCH = DATASETS / "hard-mt-2026-10-24.jsonl"
BENCH_SHA256 = "318d3c4099c327dc933b893de4e333289b19410055059c4d6cdf29c1e5d55ade"
TRAIN = ROOT / "data" / "finetune" / "quote-refuse-2026-10-17.train-x3.jsonl"
INDEXES = [
    ROOT / "data" / "index.json",
    ROOT / "data" / "index.quantization.json",
    ROOT / "data" / "index.ddia.json",
]
NEAR_RATIO = 0.85
NEAR_CONTENT_JACCARD = 0.7
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}
PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(folded):
    return {word for word in folded.split() if word not in STOPWORDS}


def load_bench():
    with BENCH.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def train_questions():
    questions = []
    with TRAIN.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            user = next((m.get("content") or "" for m in record.get("messages", [])
                         if m.get("role") == "user"), "")
            match = QUESTION_RE.search(user)
            if match:
                questions.append(fold(match.group(1)))
    return questions


class HardMultiTurnTest(unittest.TestCase):
    def test_bench_sha256_is_frozen(self):
        self.assertTrue(BENCH.is_file(), f"missing {BENCH}")
        self.assertEqual(
            hashlib.sha256(BENCH.read_bytes()).hexdigest(), BENCH_SHA256,
            "hard-mt-2026-10-24.jsonl changed. Re-run the builder, then update "
            "this constant and the one in artifacts/harnesses/hard-mt-eval.py.",
        )

    def test_shape(self):
        items = load_bench()
        self.assertEqual(len(items), 12, "bench size changed")
        ids = [item["id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
        counts = {}
        for item in items:
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        self.assertEqual(counts, {"elision": 3, "pronoun": 3,
                                  "distraction": 3, "trap": 3})
        for item in items:
            self.assertTrue(item.get("history"), f"{item['id']} has no history")
            self.assertIn(item["expect"], ("answer", "refuse"))

    def test_no_training_overlap(self):
        if not TRAIN.is_file():
            self.skipTest("training corpus not on this machine (data/ is gitignored)")
        corpus = train_questions()
        entries = [(text, content(text)) for text in corpus]
        for item in load_bench():
            folded = fold(item["question"])
            self.assertNotIn(folded, corpus, f"{item['id']} is a training question")
            words = content(folded)
            for text, text_words in entries:
                if not text_words or not words:
                    continue
                if len(words & text_words) / len(words | text_words) < NEAR_CONTENT_JACCARD:
                    continue
                ratio = difflib.SequenceMatcher(None, folded, text).ratio()
                self.assertLess(ratio, NEAR_RATIO,
                                f"{item['id']} is near {text!r} ({ratio:.3f})")

    def test_fabricated_names_are_absent_from_the_books(self):
        if not all(path.is_file() for path in INDEXES):
            self.skipTest("indexes not on this machine (data/ is gitignored)")
        text = " ".join(
            fold(chunk.get("text", ""))
            for path in INDEXES
            for chunk in json.loads(path.read_text(encoding="utf-8"))["chunks"]
        )
        for item in load_bench():
            for token in item.get("fabricated") or []:
                self.assertNotRegex(
                    text, r"\b" + re.escape(fold(token)) + r"\b",
                    f"{item['id']}: {token!r} is in a book, so refusal is wrong",
                )


if __name__ == "__main__":
    unittest.main()
