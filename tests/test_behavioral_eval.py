"""Evidence replay tests: these validate the harness, not answer-model quality."""

import sys
import json
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "artifacts" / "harnesses"
sys.path.insert(0, str(HERE))
import behavioral_eval as E


class EvidenceReplayTests(unittest.TestCase):
    def setUp(self):
        self.passage = {"chunk_id": "p1", "chapter": "1", "text": "A buffer temporarily holds records before they are written."}
        self.case = {"id": "definition", "book_id": "fixture", "question": "What is a buffer?", "expect": "answer"}
        self.result = {"refused": False, "answer": '[Ch. 1] "A buffer temporarily holds records before they are written."\nIt keeps records briefly before writing.', "citations": [{"chunk_id": "p1", "chapter": "1", "quote": self.passage["text"]}]}
        self.trace = {"trace_id": "trace-1", "retrieval": {"shown_passages": [{"chunk_id": "p1"}]}, "outcome": {"transforms": []}}
        self.capture = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")

    def test_capture_copies_evidence_instead_of_following_index_mutations(self):
        self.passage["text"] = "A different index now exists."
        self.assertIn("temporarily holds", self.capture["passages"][0]["text"])
        self.assertEqual(E.check_capture(self.capture)["defects"], [])

    def test_modified_snapshot_is_not_accepted(self):
        self.capture["passages"][0]["text"] += " Tampered."
        self.assertEqual(E.check_capture(self.capture)["status"], "unverifiable")

    def test_wrong_citation_cannot_borrow_quote_from_another_passage(self):
        other = {"chunk_id": "p2", "chapter": "1", "text": "A cache avoids repeated reads."}
        self.result["citations"][0]["chunk_id"] = "p2"
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage, other]}, self.trace, "index-digest")
        self.assertIn("wrong-citation", E.check_capture(frozen)["defects"])

    def test_one_bad_citation_is_not_hidden_by_one_good_citation(self):
        self.result["citations"].append({"chunk_id": "p1", "chapter": "1", "quote": "Invented quotation."})
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertIn("wrong-citation", E.check_capture(frozen)["defects"])

    def test_missing_original_trace_is_explicit_not_invented_claim(self):
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, {}, "index-digest")
        check = E.check_capture(frozen)
        self.assertEqual(check["status"], "unverifiable")
        self.assertNotIn("invented-claim", check["defects"])

    def test_empty_retrieval_trace_does_not_claim_original_evidence(self):
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, {"trace_id": "present", "retrieval": {"shown_passages": []}}, "index-digest")
        self.assertEqual(E.check_capture(frozen)["status"], "unverifiable")

    def test_citation_outside_the_actual_shown_set_is_flagged(self):
        other = {"chunk_id": "p2", "chapter": "1", "text": "Another source."}
        self.trace["retrieval"]["shown_passages"] = [{"chunk_id": "p2"}]
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage, other]}, self.trace, "index-digest")
        self.assertIn("unshown-citation", E.check_capture(frozen)["defects"])

    def test_answer_with_only_quote_fails_even_if_it_is_grounded(self):
        self.result["answer"] = self.result["answer"].splitlines()[0]
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertIn("missing-gloss", E.check_capture(frozen)["defects"])

    def test_question_echo_does_not_count_as_gloss(self):
        self.result["answer"] = self.result["answer"].splitlines()[0] + "\n" + self.case["question"]
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertIn("question-echo", E.check_capture(frozen)["defects"])

    def test_refusal_needs_reviewed_answerability_not_top_five_absence(self):
        self.result = {"answer": "Not in this book.", "refused": True, "citations": []}
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertEqual(E.check_capture(frozen)["status"], "unverifiable")

    def test_review_is_bound_to_question_and_index(self):
        self.case["expectation_review"] = E.review_expectation(self.case, "refuse", "index-digest", "Corpus review", "agent-source-audit")
        self.case["question"] = "A different question?"
        self.result = {"answer": "Not in this book.", "refused": True, "citations": []}
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertEqual(E.check_capture(frozen)["status"], "unverifiable")

    def test_partial_comparison_policy_does_not_falsely_reject_a_boundary_answer(self):
        self.case["expectation_review"] = E.review_expectation(self.case, "refuse", "index-digest", "Only one comparison side exists", "fixture-author")
        self.case["expectation_review"].update(coverage="partial", acceptable_behaviors=["refuse", "answer-with-boundary"])
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertNotIn("false-answer", E.check_capture(frozen)["defects"])
        calls = []
        def check_semantics(system, user):
            calls.append(user)
            return E.canonical_json(E.control_verdict("pass", frozen)), {}
        E.grade_capture(frozen, check_semantics)
        self.assertEqual(len(calls), 1)
        self.assertTrue(json.loads(calls[0])["partial_answer_allowed"])

    def test_reviewed_exact_refusal_passes_contract(self):
        self.case["expectation_review"] = E.review_expectation(self.case, "refuse", "index-digest", "Full fixture has no requested topic", "fixture-author")
        self.result = {"answer": "Not in this book.", "refused": True, "citations": []}
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertEqual(E.check_capture(frozen)["status"], "ready")
        self.assertEqual(E.check_capture(frozen)["defects"], [])

    def test_answer_and_refusal_flag_must_agree(self):
        self.result = {"answer": "Not in this book.", "refused": False, "citations": []}
        frozen = E.freeze_result(self.case, self.result, {"chunks": [self.passage]}, self.trace, "index-digest")
        self.assertIn("refusal-contract", E.check_capture(frozen)["defects"])

    def test_judge_rejects_malformed_or_incomplete_verdict(self):
        for reply in ('yes', '{}', '{"axes": {"grounded": "pass"}}'):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                E.parse_verdict(reply, self.capture)

    def test_judge_evidence_must_be_an_exact_span_in_named_passage(self):
        verdict = E.control_verdict("pass", self.capture)
        verdict["evidence"][0]["span"] = "Words that do not exist."
        with self.assertRaises(ValueError):
            E.parse_verdict(E.canonical_json(verdict), self.capture)

    def test_positive_paraphrase_and_negative_controls_are_both_required(self):
        rows = [{"id": c["id"], "expected": c["expected"], "observed": c["expected"]} for c in E.calibration_cases()]
        self.assertTrue(E.calibration_valid(rows))
        self.assertFalse(E.calibration_valid(rows[:-1]))
        rows[0]["observed"] = "fail"
        self.assertFalse(E.calibration_valid(rows))

    def test_a_reject_everything_judge_invalidates_calibration(self):
        rows = [{"id": c["id"], "expected": c["expected"], "observed": "fail"} for c in E.calibration_cases()]
        self.assertFalse(E.calibration_valid(rows))

    def test_unknowns_are_not_passes_or_hidden_from_denominator(self):
        summary = E.summarize([{"status": "pass"}, {"status": "fail"}, {"status": "unverifiable"}, {"status": "judge_error"}])
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["scored"], 2)
        self.assertEqual(summary["unverifiable"], 1)
        self.assertEqual(summary["judge_error"], 1)
        self.assertEqual(summary["pass_fraction_all"], 0.25)
        self.assertLess(summary["scored_ci95"][0], 0.5)
        self.assertGreater(summary["scored_ci95"][1], 0.5)

    def test_malformed_judge_reply_gets_one_strict_retry_with_both_attempts_retained(self):
        replies = iter([("{bad JSON", {"model_used": "fixture"}),
                        (E.canonical_json(E.control_verdict("pass", self.capture)), {"model_used": "fixture"})])
        out = E.grade_capture(self.capture, lambda system, user: next(replies))
        self.assertEqual(out["status"], "pass")
        self.assertEqual(len(out["judge_attempts"]), 2)
        self.assertIn("parse_error", out["judge_attempts"][0])
        self.assertNotEqual(out["judge_attempts"][0]["input_sha256"], out["judge_attempts"][1]["input_sha256"])

    def test_two_malformed_replies_are_judge_error_not_a_model_failure(self):
        out = E.grade_capture(self.capture, lambda system, user: ("not JSON", {"model_used": "fixture"}))
        self.assertEqual(out["status"], "judge_error")
        self.assertEqual(len(out["judge_attempts"]), 2)

    def test_passing_mock_verdict_does_not_erase_mechanical_wrong_citation(self):
        self.capture["citations"][0]["quote"] = "Invented quotation."
        calls = []
        def judge_should_not_run(*args):
            calls.append(args)
            return "{}", {}
        row = E.grade_capture(self.capture, judge_should_not_run)
        self.assertEqual(row["status"], "fail")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
