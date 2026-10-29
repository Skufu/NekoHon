"""Fairness pins for the answer-quality triage harness (offline, no judge calls).

The harness re-ranks *old* answers. Those answers saw a top-5 from their own
retrieval, so re-retrieving on replay would judge them against passages they
never had. These tests pin the fairness rules decided 2026-10-29:

- frozen evidence only, never retrieval;
- no frozen evidence -> unverifiable, never invented and never clean;
- a quote must resolve to the passage the answer cited, not to any top-5 hit;
- regex/chapter pins are advisory, never correctness;
- an unknown judge is judge_error, never invention and never a clean pass;
- owner labels are reported apart from synthetic stand-ins, and an unreviewed
  `expect` does not decide a refusal;
- completeness is a strict judge 0-3 axis (0/1 miss, 2/3 pass), and the
  no-reask bit is advisory only: nothing counts commas, demands both names in
  a comparison, or calls a short definition complete by default;
- a chapter tag never widens a citation to every passage in that chapter, and
  ambiguous chapter-only evidence is unverifiable;
- existing evidence files are never overwritten by accident.
"""

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))


def load_rank_answers():
    spec = importlib.util.spec_from_file_location(
        "rank_answers_harness", ROOT / "artifacts" / "harnesses" / "rank-answers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = load_rank_answers()

GOOD_QUOTE = "Storage is the cornerstone of the data engineering lifecycle"
OTHER_QUOTE = "Batch processing handles large volumes of data on a schedule"
NOWHERE_QUOTE = "Data warehouses always cost less than data lakes in every deployment"

PASSAGES = [
    {
        "chunk_id": "ch01-001",
        "chapter": "1",
        "text": GOOD_QUOTE + ". A watermark is a threshold used to detect when data is complete.",
        "shown": True,
    },
    {
        "chunk_id": "ch02-002",
        "chapter": "2",
        "text": OTHER_QUOTE + ". It reads the accumulated files at intervals.",
        "shown": True,
    },
    {
        "chunk_id": "ch03-003",
        "chapter": "3",
        "text": "Streaming processes each event as it arrives.",
        "shown": True,
    },
]

DEFAULT_BITS = {
    "answers_question": "yes",
    "grounded": "yes",
    "clean_form": "yes",
    "no_reask": "no",  # the good value for the no-reask bit
}


def fake_judge(**overrides):
    """A judge double: per-bit value or a three-vote sequence."""
    table = dict(DEFAULT_BITS)
    table.update(overrides)
    queues = {}

    def call(bit, question, passages_text, answer_text, timeout):
        value = table[bit]
        if isinstance(value, (list, tuple)):
            queue = queues.setdefault(bit, list(value))
            return queue.pop(0) if queue else "judge_error"
        return value

    return call


def make_row(**overrides):
    row = {
        "id": 1,
        "question": "What is storage?",
        "mode": "answer",
        "answer": f'[Ch. 1] "{GOOD_QUOTE}"\nStorage keeps the data the rest of the pipeline depends on.',
        "refused": False,
        "chapters": ["1"],
        "passages": PASSAGES,
        "expect": "answer",
        "gold_chunks": ["ch01-001"],
        "key_fact": "storage",
        "source": "test",
    }
    row.update(overrides)
    return row


def fake_complete(value="3"):
    """A completeness-axis double: a strict 0-3 reply, or a raised backend."""
    def call(question, passages_text, answer_text, timeout):
        if isinstance(value, BaseException):
            raise value
        return value
    return call


def judge(row, complete="3", **overrides):
    return MOD.judge_row(
        row,
        judge_call=fake_judge(**overrides),
        complete_call=fake_complete(complete),
        judge_label="test:judge",
        pace=0,
    )


class NoRetrievalOnReplayTest(unittest.TestCase):
    def test_harness_does_not_import_retrieval(self):
        src = (ROOT / "artifacts" / "harnesses" / "rank-answers.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("from retrieve", src)
        self.assertNotIn("retrieval_context", src)
        self.assertFalse(hasattr(MOD, "retrieval_context"))

    def test_replay_never_calls_retrieval(self):
        with mock.patch.object(
            MOD.A, "retrieval_context", side_effect=AssertionError("re-retrieved")
        ):
            out = judge(make_row())
        self.assertEqual(out["defect"], "none")
        self.assertEqual(out["evidence_state"], "frozen")

    def test_frozen_passage_without_text_is_unverifiable(self):
        row = make_row(passages=[{"chunk_id": "ch01-001", "chapter": "1"}])
        out = judge(row)
        self.assertEqual(out["defect"], "unverifiable")
        self.assertFalse(MOD.scorable(out))


class MissingEvidenceTest(unittest.TestCase):
    def test_corrupt_frozen_passage_hash_is_unverifiable(self):
        row = make_row(passages=[dict(p, sha256="tampered") for p in PASSAGES])
        out = judge(row)
        self.assertEqual(out["defect"], "unverifiable")
        self.assertTrue(out["evidence_missing"])

    def test_legacy_row_is_unverifiable_not_invented_not_clean(self):
        row = make_row()
        row.pop("passages")
        out = judge(row)
        self.assertEqual(out["defect"], "unverifiable")
        self.assertIsNone(out["quote_ok"])
        self.assertTrue(out["evidence_missing"])
        self.assertFalse(MOD.scorable(out))
        self.assertTrue(MOD.flagged(out))
        self.assertEqual(MOD.rank_tier(out), 1)

    def test_missing_evidence_never_becomes_invented_claim(self):
        row = make_row()
        row.pop("passages")
        row["answer"] = f'[Ch. 1] "{NOWHERE_QUOTE}"\nA claim with no source.'
        out = judge(row)
        self.assertNotEqual(out["defect"], "invented-claim")
        self.assertIsNone(out["quote_ok"])


class QuoteCitationTest(unittest.TestCase):
    def test_quote_in_cited_passage_is_ok(self):
        out = judge(make_row())
        self.assertIs(out["quote_ok"], True)
        self.assertEqual(out["defect"], "none")

    def test_quote_only_in_an_uncited_top5_passage_is_wrong_citation(self):
        row = make_row(
            answer=f'[Ch. 1] "{OTHER_QUOTE}"\nA batch job runs on a schedule.'
        )
        out = judge(row)
        self.assertEqual(out["quote_ok"], "elsewhere")
        self.assertEqual(out["defect"], "wrong-citation")
        self.assertEqual(MOD.rank_tier(out), 0)

    def test_quote_in_no_frozen_passage_is_invented_claim(self):
        row = make_row(answer=f'[Ch. 1] "{NOWHERE_QUOTE}"\nA fabricated sentence.')
        out = judge(row)
        self.assertIs(out["quote_ok"], False)
        self.assertEqual(out["defect"], "invented-claim")

    def test_quote_without_a_resolved_citation_is_uncited(self):
        row = make_row(answer=f'"{GOOD_QUOTE}"\nStorage keeps the pipeline going.')
        row["chapters"] = []
        out = judge(row)
        self.assertIsNone(out["quote_ok"])
        self.assertEqual(out["defect"], "uncited")
        self.assertEqual(MOD.rank_tier(out), 0)

    def test_explicit_citation_does_not_widen_to_the_rest_of_the_chapter(self):
        passages = [
            {"chunk_id": "ch01-001", "chapter": "1",
             "text": GOOD_QUOTE + ". Storage keeps the pipeline going.", "shown": True},
            {"chunk_id": "ch01-002", "chapter": "1",
             "text": "A watermark is a threshold that detects complete data.", "shown": True},
        ]
        row = make_row(
            passages=passages,
            chapters=["1"],
            citations=[{"chunk_id": "ch01-002"}],
            answer=f'[Ch. 1] "{GOOD_QUOTE}"\nStorage keeps the pipeline going.',
        )
        out = judge(row)
        self.assertEqual(out["cited_chunks"], ["ch01-002"])
        self.assertIs(out["quote_ok"], "elsewhere")
        self.assertEqual(out["defect"], "wrong-citation")

    def test_chapter_only_evidence_with_several_matches_is_ambiguous(self):
        passages = [
            {"chunk_id": "ch01-001", "chapter": "1",
             "text": GOOD_QUOTE + ". Storage keeps the pipeline going.", "shown": True},
            {"chunk_id": "ch01-002", "chapter": "1",
             "text": "A watermark is a threshold that detects complete data.", "shown": True},
        ]
        row = make_row(
            passages=passages,
            chapters=["1"],
            answer=f'[Ch. 1] "{GOOD_QUOTE}"\nStorage keeps the pipeline going.',
        )
        out = judge(row)
        self.assertEqual(out["ambiguous_cited_chapters"], ["1"])
        self.assertEqual(out["cited_chunks"], [])
        self.assertIsNone(out["quote_ok"])
        self.assertEqual(out["defect"], "unverifiable")

    def test_a_chapter_matching_exactly_one_passage_still_resolves(self):
        row = make_row(passages=[PASSAGES[0]], chapters=["1"], citations=[])
        out = judge(row)
        self.assertEqual(out["cited_chunks"], ["ch01-001"])
        self.assertIs(out["quote_ok"], True)
        self.assertEqual(out["defect"], "none")

    def test_explicit_citation_with_no_frozen_text_is_unverifiable(self):
        row = make_row(
            citations=[{"chunk_id": "ch07-777"}],
            answer=f'[Ch. 7] "{NOWHERE_QUOTE}"\nA claim whose source was not frozen.',
        )
        out = judge(row)
        self.assertEqual(out["cited_unresolved"], ["ch07-777"])
        self.assertIsNone(out["quote_ok"])
        self.assertEqual(out["defect"], "unverifiable")
        self.assertNotEqual(out["defect"], "invented-claim")


class JudgeErrorTest(unittest.TestCase):
    def test_unknown_reply_is_judge_error_not_invention_not_clean(self):
        out = judge(make_row(), **{bit: "banana" for bit in MOD.BITS})
        self.assertEqual(out["defect"], "judge_error")
        self.assertNotIn(out["defect"], ("invented-claim", "none"))
        self.assertTrue(MOD.flagged(out))
        self.assertFalse(MOD.scorable(out))

    def test_two_of_three_errors_is_judge_error(self):
        out = judge(
            make_row(),
            answers_question=["judge_error", "judge_error", "yes"],
        )
        self.assertEqual(out["defect"], "judge_error")

    def test_one_yes_one_no_one_error_is_not_a_pass(self):
        out = judge(make_row(), answers_question=["yes", "no", "judge_error"])
        self.assertEqual(out["defect"], "judge_error")

    def test_two_of_three_votes_majority(self):
        out = judge(make_row(), answers_question=["yes", "yes", "no"])
        self.assertEqual(out["answers_question"], "yes")
        self.assertEqual(out["defect"], "none")


class AdvisoryPinsTest(unittest.TestCase):
    def test_failed_gold_chapter_and_key_fact_regex_do_not_make_a_defect(self):
        box = make_row(key_fact="zzzz-not-in-answer", gold_chunks=["ch09-999"])
        out = judge(box)
        self.assertIs(out["gold_cited"], False)
        self.assertIs(out["key_fact_present"], False)
        self.assertEqual(out["defect"], "none")
        self.assertFalse(MOD.flagged(out))
        self.assertEqual(MOD.rank_tier(out), 2)


class CompletenessAxisTest(unittest.TestCase):
    """The judge's 0-3 axis decides completeness; the harness only labels it."""

    def test_concise_definition_passes_when_the_judge_finds_the_content(self):
        row = make_row(
            question="Snowflake",
            answer=f'[Ch. 1] "{GOOD_QUOTE}"\nSnowflake divides data into small groups of rows.',
            no_reask="yes",
        )
        out = judge(row, no_reask="yes", complete="3")
        self.assertEqual(out["question_kind"], "other")
        self.assertTrue(out["no_reask_advisory"])
        self.assertEqual(out["defect"], "none")

    def test_definition_with_missing_content_is_a_real_fail(self):
        row = make_row(
            question="Snowflake",
            answer=f'[Ch. 1] "{GOOD_QUOTE}"\nSnowflake is a thing.',
        )
        out = judge(row, complete="1")
        self.assertEqual(out["defect"], "incomplete")

    def test_axis_two_passes(self):
        out = judge(make_row(), complete="2")
        self.assertEqual(out["defect"], "none")

    def test_natural_prose_list_passes_without_comma_counting(self):
        row = make_row(
            question="What are the advantages of batch processing?",
            answer=(
                f'[Ch. 2] "{OTHER_QUOTE}"\n'
                "The advantages are that it is simpler to operate and easier "
                "to recover after a failure."
            ),
        )
        out = judge(row, complete="3")
        self.assertEqual(out["question_kind"], "list")
        self.assertEqual(out["defect"], "none")

    def test_missing_list_fails_on_the_axis_not_on_punctuation(self):
        row = make_row(
            question="What are the advantages of batch processing?",
            answer=f'[Ch. 2] "{OTHER_QUOTE}"\nThere are several factors to consider.',
        )
        out = judge(row, complete="0")
        self.assertEqual(out["question_kind"], "list")
        self.assertEqual(out["defect"], "incomplete-list")

    def test_both_names_without_a_contrast_still_fails(self):
        row = make_row(
            question="monolith vs modular",
            answer=(
                f'[Ch. 1] "{GOOD_QUOTE}"\n'
                "Monolith and modular are both discussed in the book."
            ),
        )
        out = judge(row, complete="1")
        self.assertEqual(out["question_kind"], "comparison")
        self.assertEqual(out["defect"], "incomplete-comparison")

    def test_two_sided_comparison_passes_when_the_judge_says_complete(self):
        row = make_row(
            question="How does batch processing differ from streaming?",
            answer=(
                f'[Ch. 2] "{OTHER_QUOTE}"\n'
                "Batch processing runs on a schedule, while streaming handles each event."
            ),
        )
        out = judge(row, complete="3")
        self.assertEqual(out["defect"], "none")

    def test_no_reask_is_advisory_and_never_a_defect(self):
        row = make_row(question="Tell me about storage.")
        out = judge(row, no_reask="yes", complete="3")
        self.assertTrue(out["no_reask_advisory"])
        self.assertEqual(out["defect"], "none")

    def test_invalid_axis_is_judge_error_never_a_pass(self):
        for axis in ("9", "banana", "", None):
            with self.subTest(axis=axis):
                out = judge(make_row(), complete=axis)
                self.assertEqual(out["defect"], "judge_error")
                self.assertFalse(MOD.scorable(out))

    def test_axis_backend_failure_is_judge_error(self):
        out = judge(make_row(), complete=RuntimeError("relay down"))
        self.assertEqual(out["defect"], "judge_error")
        self.assertIn("complete_error", out)

    def test_axis_is_not_called_without_frozen_evidence_or_on_a_refusal(self):
        row = make_row()
        row.pop("passages")
        out = judge(row, complete=AssertionError("should not be called"))
        self.assertEqual(out["defect"], "unverifiable")
        self.assertEqual(out["completeness"]["verdict"], "not-checked")

        refused = make_row(answer="Not in this book.", refused=True, chapters=[])
        out = judge(refused, complete=AssertionError("should not be called"))
        self.assertEqual(out["defect"], "unreviewed-answerability")


class AnswerabilityReviewTest(unittest.TestCase):
    def test_unreviewed_expect_does_not_decide_a_refusal(self):
        row = make_row(
            id=13,
            question="ddr4 vs ddr5",
            answer="Not in this book.",
            refused=True,
            chapters=[],
        )
        out = judge(row)
        self.assertEqual(out["defect"], "unreviewed-answerability")
        self.assertIsNone(out["refusal_ok"])
        self.assertIs(out["refusal_ok_advisory"], False)
        self.assertFalse(MOD.scorable(out))

    def test_reviewed_answer_against_a_refusal_is_false_refusal(self):
        row = make_row(
            answer="Not in this book.",
            refused=True,
            chapters=[],
            expectation_review={
                "expect": "answer",
                "reason": "the book covers storage",
                "reviewer": "owner",
            },
        )
        out = judge(row)
        self.assertEqual(out["defect"], "false-refusal")
        self.assertIs(out["refusal_ok"], False)
        self.assertEqual(MOD.rank_tier(out), 0)

    def test_reviewed_refusal_matching_the_answer_is_clean(self):
        row = make_row(
            question="What is the capital of France?",
            answer="Not in this book.",
            refused=True,
            chapters=[],
            expectation_review={
                "expect": "refuse",
                "reason": "no France content in the book",
                "reviewer": "owner",
            },
        )
        out = judge(row)
        self.assertEqual(out["defect"], "none")
        self.assertIs(out["refusal_ok"], True)
        self.assertFalse(MOD.flagged(out))


class ProvenanceTest(unittest.TestCase):
    def test_row_carries_question_answer_prompt_votes_models_and_evidence_hash(self):
        row = make_row(answer_model="test-model", index_sha256="abc123")
        out = judge(row)
        prov = out["provenance"]
        self.assertEqual(prov["question_sha256"], MOD.digest(row["question"]))
        self.assertEqual(prov["answer_sha256"], MOD.digest(row["answer"]))
        self.assertEqual(prov["judge"], "test:judge")
        self.assertEqual(prov["answer_model"], "test-model")
        self.assertEqual(prov["index_sha256"], "abc123")
        self.assertEqual(set(prov["prompt_sha256"]), set(MOD.BITS))
        self.assertEqual(
            prov["complete_prompt_sha256"], MOD.digest(MOD.J.COMPLETE_SYSTEM)
        )
        self.assertEqual(prov["complete_axis"], "3")
        self.assertEqual(prov["raw_votes"], out["votes"])
        self.assertEqual(prov["evidence_sha256"], out["evidence_sha256"])
        self.assertEqual(prov["evidence_state"], "frozen")
        self.assertEqual(prov["harness_version"], MOD.HARNESS_VERSION)

    def test_evidence_hash_is_stable_for_the_same_frozen_passages(self):
        first = judge(make_row())
        second = judge(make_row())
        self.assertEqual(first["evidence_sha256"], second["evidence_sha256"])

    def test_unknown_answer_model_is_recorded_as_unknown(self):
        row = make_row()
        row.pop("answer_model", None)
        self.assertEqual(judge(row)["provenance"]["answer_model"], "unknown")


class RaterSeparationTest(unittest.TestCase):
    def test_owner_and_synthetic_labels_are_reported_separately(self):
        rows = [
            {"id": 1, "defect": "unverifiable", "rating": "good"},
            {"id": 2, "defect": "none", "rating": "good"},
            {"id": 3, "defect": "invented-claim", "persona_rating": "bad"},
        ]
        lines = MOD.rater_summary(rows)
        text = "\n".join(lines)
        self.assertIn("rating (owner labels)", text)
        self.assertIn("persona_rating (synthetic stand-in labels)", text)
        self.assertIn("unscored 1/2", text)  # one unverifiable of two owner rows
        self.assertIn("bads flagged 1/1", text)

    def test_unverifiable_rows_are_not_scored_against_labels(self):
        rows = [{"id": 1, "defect": "unverifiable", "rating": "bad"}]
        self.assertEqual(MOD.rater_summary(rows), [
            "# rating (owner labels): agreement 0/0 | bads flagged 0/0 | unscored 1/1"
        ])


class EvidenceWriteGuardTest(unittest.TestCase):
    def test_existing_evidence_is_not_overwritten_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answer-quality-old.json"
            path.write_text("{}", encoding="utf-8")
            err = io.StringIO()
            with mock.patch.object(sys, "stderr", err):
                with self.assertRaises(SystemExit) as cm:
                    MOD.ensure_writable(path, overwrite=False)
            self.assertEqual(cm.exception.code, 3)
            self.assertIn("refusing to overwrite", err.getvalue())
            self.assertEqual(path.read_text(encoding="utf-8"), "{}")

    def test_missing_evidence_path_is_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            MOD.ensure_writable(Path(tmp) / "new.json", overwrite=False)


class ParentVerifiedDatasetTest(unittest.TestCase):
    """The parent's verified facts about the only owner-rated dataset."""

    @classmethod
    def setUpClass(cls):
        path = ROOT / "artifacts" / "datasets" / "owner-rated-2026-10-15.jsonl"
        cls.rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_dataset_has_27_rows(self):
        self.assertEqual(len(self.rows), 27)

    def test_only_rows_25_to_27_carry_owner_ratings(self):
        rated = [r["id"] for r in self.rows if r.get("rating")]
        self.assertEqual(rated, [25, 26, 27])

    def test_row_13_expects_an_answer_but_has_no_review_or_frozen_evidence(self):
        row = next(r for r in self.rows if r["id"] == 13)
        self.assertEqual(row["question"], "ddr4 vs ddr5")
        self.assertEqual(row["expect"], "answer")
        self.assertIsNone(row.get("expectation_review"))
        self.assertFalse(row.get("passages"))
        self.assertIsNone(MOD.reviewed_expect(row))

    def test_row_13_refusal_is_unreviewed_answerability(self):
        row = next(r for r in self.rows if r["id"] == 13)
        out = judge(row)
        self.assertEqual(out["defect"], "unreviewed-answerability")
        self.assertIsNone(out["refusal_ok"])

    def test_index_really_has_no_ddr4_and_one_ddr5_chunk(self):
        index_path = ROOT / "data" / "index.json"
        if not index_path.exists():
            self.skipTest("data/index.json is gitignored and absent on this machine")
        chunks = json.loads(index_path.read_text(encoding="utf-8"))["chunks"]

        def count(token):
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + token + r"(?![A-Za-z0-9])", re.I
            )
            return sum(1 for c in chunks if pattern.search(c.get("text") or ""))

        # Parent verification 2026-10-29: the pin says "answer" for row 13,
        # but DDR4 never appears in the book and DDR5 appears once.
        self.assertEqual(count("DDR4"), 0)
        self.assertEqual(count("DDR5"), 1)


if __name__ == "__main__":
    unittest.main()
