"""No eval question may appear in the finetune corpus.

Why this test exists: the training file was authored from the same book the
eval sets score, so question overlap is the way a "hold-out" quietly stops
being held out. `qa-questions-overnight.json` is the proof — 81 of its 124
questions are verbatim training rows, so it cannot be a test.

Rules asserted here:

1. `sealed-2026-10-24.jsonl` matches its frozen sha256. Changing the set is a
   deliberate act, and this test is the tripwire.
2. hard-bench, wide-net and the sealed set have zero exact and zero
   near-duplicate questions against the training corpus.
3. adrian has exactly the one known leak, `adrian-18`. Anything else is new.
4. `qa-questions-overnight.json` is not listed as a sealed eval surface.

The training file is gitignored. On a machine without it the corpus checks
skip; the sha256 freeze still runs.
"""

import difflib
import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "data" / "finetune" / "quote-refuse-2026-10-16.train-x2f.jsonl"
DATASETS = ROOT / "artifacts" / "datasets"
SEALED = DATASETS / "sealed-2026-10-24.jsonl"
SEALED_SHA256 = "24fcc1c9138e158d26891a88bb07d5ef1e9eeb21bcbe137aa40d00961404d0d7"
NEAR_RATIO = 0.85
# Short questions are string-similar without asking the same thing:
# "what is replication" vs "what is location" scores 0.857. A near-duplicate
# must also share its content words, so both guards apply.
NEAR_CONTENT_JACCARD = 0.7
STOPWORDS = {
    "what", "is", "are", "the", "a", "an", "of", "in", "to", "do", "does",
    "did", "how", "why", "which", "for", "and", "it", "its", "this", "that",
    "these", "those", "was", "were", "be", "by", "on", "with", "can",
}
KNOWN_ADRIAN_LEAKS = {"adrian-18"}
TRAINING_DERIVED = {"qa-questions-overnight.json"}

PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
SPACE_RE = re.compile(r"\s+")
QUESTION_RE = re.compile(r"^Question:\s*(.+?)(?:\n\n|\Z)", re.S | re.M)


def fold(text):
    return SPACE_RE.sub(" ", PUNCT_RE.sub(" ", (text or "").lower())).strip()


def content(folded):
    return {word for word in folded.split() if word not in STOPWORDS}


def train_questions(path=TRAIN):
    questions = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            user = next(
                (m.get("content") or "" for m in record.get("messages", [])
                 if m.get("role") == "user"),
                "",
            )
            match = QUESTION_RE.search(user)
            if match:
                questions.append(fold(match.group(1)))
    return questions


def jsonl_questions(path):
    items = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            question = record.get("question") or record.get("prompt") or ""
            if not question and record.get("selection"):
                question = "[selection] " + record["selection"]
            if question:
                items.append((record.get("id"), question))
    return items


def adrian_questions(path=DATASETS / "adrian-realworld-eval-2026-10-17.json"):
    items = []
    with path.open(encoding="utf-8") as fh:
        for scenario in json.load(fh):
            for turn in scenario.get("turns") or []:
                question = turn.get("question") or ""
                if not question and turn.get("selection"):
                    question = "[selection] " + turn["selection"]
                if question:
                    items.append((scenario.get("id"), question))
    return items


def leaks(questions, corpus):
    """[(id, question, kind)] where kind is 'exact' or 'near <ratio>'."""
    found = []
    corpus_entries = [(text, content(text)) for text in corpus]
    for item_id, question in questions:
        folded = fold(question)
        if not folded:
            continue
        if folded in corpus:
            found.append((item_id, question, "exact"))
            continue
        words = content(folded)
        if not words:
            continue
        best = 0.0
        for text, text_words in corpus_entries:
            if not text_words:
                continue
            overlap = len(words & text_words) / len(words | text_words)
            if overlap < NEAR_CONTENT_JACCARD:
                continue
            best = max(best, difflib.SequenceMatcher(None, folded, text).ratio())
        if best >= NEAR_RATIO:
            found.append((item_id, question, f"near {best:.3f}"))
    return found


class SealedSetTest(unittest.TestCase):
    def test_sealed_sha256_is_frozen(self):
        self.assertTrue(SEALED.is_file(), f"missing {SEALED}")
        # Line endings are not content: the repo stores LF, a Windows working
        # copy may hold CRLF, and this freeze is about the questions.
        digest = hashlib.sha256(SEALED.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self.assertEqual(
            digest,
            SEALED_SHA256,
            "sealed-2026-10-24.jsonl changed. If that was deliberate, update the "
            "constant here and in artifacts/harnesses/sealed-eval.py, and re-run "
            "the leakage audit.",
        )

    def test_sealed_set_has_no_training_overlap(self):
        self.assertTrue(SEALED.is_file())
        items = jsonl_questions(SEALED)
        self.assertEqual(len(items), 30, "sealed set size changed")
        ids = [item_id for item_id, _ in items]
        self.assertEqual(len(ids), len(set(ids)), "duplicate sealed ids")
        if not TRAIN.is_file():
            self.skipTest("training corpus not on this machine (data/ is gitignored)")
        found = leaks(items, train_questions())
        self.assertEqual(found, [], f"sealed questions leak training rows: {found}")

    def test_shipped_benchmarks_have_no_training_overlap(self):
        if not TRAIN.is_file():
            self.skipTest("training corpus not on this machine (data/ is gitignored)")
        corpus = train_questions()
        for name in ("hard-bench-2026-10-17.jsonl", "wide-net-2026-10-23.jsonl"):
            found = leaks(jsonl_questions(DATASETS / name), corpus)
            self.assertEqual(found, [], f"{name} leaks training rows: {found}")

    def test_adrian_has_only_the_known_leak(self):
        if not TRAIN.is_file():
            self.skipTest("training corpus not on this machine (data/ is gitignored)")
        found = leaks(adrian_questions(), train_questions())
        ids = {item_id for item_id, _, _ in found}
        self.assertEqual(
            ids,
            KNOWN_ADRIAN_LEAKS,
            "adrian leakage changed. New leaks must be fixed in the training "
            "data, not allowlisted. Known: adrian-18 ('What is change data "
            "capture?') is verbatim in the x2f corpus.",
        )

    def test_training_derived_files_are_not_eval_surfaces(self):
        for name in TRAINING_DERIVED:
            self.assertNotIn(name, (DATASETS / "sealed-2026-10-24.jsonl").name)
            text = (ROOT / "artifacts" / "harnesses" / "sealed-eval.py").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(name, text, f"{name} is training-derived and cannot score the model")


if __name__ == "__main__":
    unittest.main()
