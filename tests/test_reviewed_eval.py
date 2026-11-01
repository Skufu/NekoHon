"""Reviewed-response evaluation: what a model/system output may be called PASS.

Every fixture here is synthetic and offline. Nothing calls a model, a judge, an
index, or the network. The tests exist because an evaluator can be worse than
no evaluator: a correct quote plus a generic paragraph must not pass, a forged
quote must not validate against another chunk, and a review must stop applying
the moment the response, evidence, question, reference, or criterion changes.

The rule under test is versioned (`reviewed-semantics-v2`). A v1 review was
signed before quote attribution became structural, so it goes stale instead of
being retroactively certified. The old failed Go judge v3 calibration is
retained elsewhere and is never read here; a review carrying that criterion
version is stale, not a pass.

Module: `artifacts/harnesses/reviewed_eval.py`.
Schema note: `artifacts/runs/data-repair-2026-10-29/evaluation/REVIEW-SCHEMA.md`.
"""

import copy
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import reviewed_eval as RE  # noqa: E402

S1 = (
    "A watermark is a threshold used to track the progress of a stream. "
    "It moves with the data."
)
S2 = "Batch processing handles bounded data, while stream processing handles unbounded data."
S3 = "Schema evolution changes a table without a rewrite."
FACT = "A watermark tracks the progress of a stream."
GOOD_BODY = (
    '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."\n'
    "A watermark tracks how far the incoming records have advanced."
)
PARAPHRASE = (
    "[Ch. 8] It keeps count of how far the incoming records have advanced and "
    "uses that point to decide when to emit results."
)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ref(source_id, chunk_id, chapter, text, spans=None):
    return {
        "source_id": source_id,
        "book_id": "fde",
        "index_path": "data/index.sqlite",
        "index_sha256": "0" * 64,
        "chunk_id": chunk_id,
        "chapter": chapter,
        "text_sha256": digest(text),
        "spans": spans
        if spans is not None
        else [{"start": 0, "end": len("A watermark is a threshold"), "text": "A watermark is a threshold"}],
    }


def shown(source_id, chunk_id, chapter, text):
    return {
        "source_id": source_id,
        "book_id": "fde",
        "chunk_id": chunk_id,
        "chapter": chapter,
        "text": text,
    }


def golden(**over):
    record = {
        "schema_version": 1,
        "id": "g-watermark",
        "family_id": "watermark",
        "split": "dev",
        "book_id": "fde",
        "question": "What is a watermark?",
        "history": [],
        "provided_source_ids": ["fde:ch08-039"],
        "source_refs": [ref("fde:ch08-039", "ch08-039", "8", S1)],
        "expected": {
            "book_answerable": True,
            "evidence_sufficient": True,
            "allowed_behaviors": ["answer"],
            "required_facts": [{"claim": FACT, "source_ids": ["fde:ch08-039"]}],
            "unsupported_claims": [],
        },
        "review": {
            "status": "accepted",
            "author": "gold-author",
            "reviewer": "gold-reviewer",
            "provenance": "agent",
            "notes": "synthetic fixture",
        },
        "origin": {
            "path": "tests/test_reviewed_eval.py",
            "sha256": "0" * 64,
            "record": 1,
            "kind": "authored",
        },
        "target_kind": "answer",
    }
    record.update(over)
    review_block = record.get("review")
    if isinstance(review_block, dict) and review_block.get("status") == "accepted":
        review_block.setdefault("content_sha256", RE.content_digest(record))
        review_block.setdefault("criteria_version", "golden-content-v1")
    return copy.deepcopy(record)


def response(body=GOOD_BODY, **over):
    record = {
        "schema_version": 1,
        "response_id": "r1",
        "golden_id": "g-watermark",
        "task_stage": "model",
        "capture": {"status": "ok"},
        "input": {"question": "What is a watermark?", "history": []},
        "evidence": {
            "status": "shown",
            "sources": [
                shown("fde:ch08-039", "ch08-039", "8", S1),
                shown("fde:ch02-022", "ch02-022", "2", S2),
            ],
        },
        "model": {
            "raw_body": body,
            "provenance": "model",
            "tag": "test-model",
            "digest": "abc123",
            "done_reason": "stop",
        },
        "reader": {
            "final_text": body,
            "provenance": "engine",
            "code_fallback": False,
            "citations": [{"chapter": "8", "chunk_id": "ch08-039"}],
        },
    }
    record.update(over)
    return copy.deepcopy(record)


def review(g, r, stage="model", **over):
    record = {
        "schema_version": 1,
        "review_id": "rev1",
        "golden_id": g["id"],
        "response_id": r["response_id"],
        "stage": stage,
        "bind": RE.bindings_for(g, r, stage),
        "verdict": "pass",
        "behavior": "answer",
        "rationale": "The gloss says what the quoted sentence says, in other words.",
        "facts": [
            {
                "fact_index": 0,
                "status": "supported",
                "witness": {
                    "source_id": "fde:ch08-039",
                    "quote": "A watermark is a threshold used to track the progress of a stream.",
                },
            }
        ],
        "unsupported_claims": [],
        "utility": {
            "answers_question": True,
            "rationale": "It explains the tracking role instead of only copying the quote.",
        },
        "ambiguity": None,
        "reviewer": "reviewer-2",
        "provenance": "agent",
        "reviewed_at": "2026-10-29",
    }
    record.update(over)
    return copy.deepcopy(record)


def one(report, stage="model", response_id="r1"):
    matches = [
        rec
        for rec in report["records"]
        if rec.get("stage") == stage and rec.get("response_id") == response_id
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one {stage} record for {response_id}, got {len(matches)}: "
            f"{[(rec.get('stage'), rec.get('response_id')) for rec in report['records']]}"
        )
    return matches[0]


def codes(record):
    return set(record.get("causes") or [])


class ReviewedEvalTests(unittest.TestCase):
    # -- negative controls: none of these may pass -------------------------

    def test_echo_is_fail(self):
        report = RE.evaluate([golden()], [response("What is a watermark?")], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("echo_not_an_answer", codes(record))

    def test_echo_with_a_tag_is_still_an_echo(self):
        report = RE.evaluate([golden()], [response("[Ch. 8] What is a watermark?")], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("echo_not_an_answer", codes(record))

    def test_model_stage_needs_a_visible_tag_not_engine_metadata(self):
        g = golden()
        r = response("It keeps count of how far the incoming records have advanced.")
        r["model"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-039"}]
        report = RE.evaluate([g], [r], [review(g, r)], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("answer_uncited", codes(record))

    def test_chapter_label_with_title_matches_a_numeric_tag(self):
        g = golden()
        g["source_refs"][0]["chapter"] = "Chapter 8. Storage"
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response(
            GOOD_BODY,
            evidence={
                "status": "shown",
                "sources": [shown("fde:ch08-039", "ch08-039", "Chapter 8. Storage", S1)],
            },
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
        self.assertNotIn("cited_chapter_not_shown", codes(record))

    def appendix_golden(self, source_id, chunk_id, chapter, text, question):
        return golden(
            question=question,
            provided_source_ids=[source_id],
            source_refs=[ref(source_id, chunk_id, chapter, text, spans=[])],
            expected={
                "book_answerable": True,
                "evidence_sufficient": True,
                "allowed_behaviors": ["answer"],
                "required_facts": [
                    {"claim": "Schema evolution changes a table without a rewrite.", "source_ids": [source_id]}
                ],
                "unsupported_claims": [],
            },
        )

    def appendix_record(self, g, body, sources, witness=None):
        r = response(
            body,
            input={"question": g["question"], "history": []},
            evidence={"status": "shown", "sources": sources},
        )
        rev = review(g, r)
        witness = witness or sources[0]
        rev["facts"] = [
            {
                "fact_index": 0,
                "status": "supported",
                "witness": {"source_id": witness["source_id"], "quote": witness["text"]},
            }
        ]
        return RE.evaluate([g], [r], [rev], self_check=False)

    def test_appendix_chapter_label_resolves_in_a_tag(self):
        """A capture labelled ``Appendix A: Tables`` answers ``[Ch. appendix-a]``."""
        g = self.appendix_golden(
            "fde:chA-001", "chA-001", "Appendix A: Tables", S3, "What does schema evolution change?"
        )
        sources = [shown("fde:chA-001", "chA-001", "Appendix A: Tables", S3)]
        body = (
            '[Ch. appendix-a] "Schema evolution changes a table without a rewrite."\n'
            "A table can change in place."
        )
        record = one(self.appendix_record(g, body, sources))
        self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
        self.assertEqual(record["status"], "PASS", record["causes"])

    def test_chapter_range_and_slash_tags_resolve_each_member(self):
        """``[Ch. 8-9]`` and ``[Ch. 8/9]`` cite chapter 9 as well as chapter 8."""
        g = golden(
            question="What does schema evolution change?",
            provided_source_ids=["fde:ch08-039", "fde:ch09-001"],
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch09-001", "ch09-001", "9", S3, spans=[]),
            ],
            expected={
                "book_answerable": True,
                "evidence_sufficient": True,
                "allowed_behaviors": ["answer"],
                "required_facts": [
                    {"claim": "Schema evolution changes a table without a rewrite.", "source_ids": ["fde:ch09-001"]}
                ],
                "unsupported_claims": [],
            },
        )
        sources = [
            shown("fde:ch08-039", "ch08-039", "8", S1),
            shown("fde:ch09-001", "ch09-001", "9", S3),
        ]
        for tag in ("[Ch. 8-9]", "[Ch. 8/9]"):
            with self.subTest(tag=tag):
                body = (
                    f'{tag} "Schema evolution changes a table without a rewrite."\n'
                    "A table can change in place."
                )
                record = one(self.appendix_record(g, body, sources, witness=sources[1]))
                self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
                self.assertEqual(record["status"], "PASS", record["causes"])

    def test_appendix_number_never_resolves_a_chapter_tag(self):
        """``[Ch. 4]`` does not reach a capture whose chapter is ``Appendix 4``."""
        g = self.appendix_golden(
            "fde:chA-004", "chA-004", "Appendix 4", S3, "What does schema evolution change?"
        )
        sources = [shown("fde:chA-004", "chA-004", "Appendix 4", S3)]
        body = (
            '[Ch. 4] "Schema evolution changes a table without a rewrite."\n'
            "A table can change in place."
        )
        record = one(self.appendix_record(g, body, sources))
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("cited_chapter_not_shown", codes(record))

    def test_guard_no_call_answer_is_unverifiable(self):
        g = golden()
        r = response(
            PARAPHRASE,
            capture={"status": "no_call"},
            evidence={"status": "guard_no_call", "sources": []},
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("guard_no_model_call_answer", codes(record))
        self.assertNotIn("quote_not_in_shown_evidence", codes(record))

    def test_correct_quote_with_generic_gloss_cannot_auto_pass(self):
        body = (
            '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."\n'
            "Data engineering is a broad field with many practices and tools."
        )
        without_review = RE.evaluate([golden()], [response(body)], self_check=False)
        self.assertNotEqual(one(without_review)["status"], "PASS")
        self.assertEqual(one(without_review)["semantic"]["status"], "REVIEW")

        g = golden()
        r = response(body)
        lying = review(g, r, facts=[])
        with_lie = RE.evaluate([g], [r], [lying], self_check=False)
        self.assertEqual(one(with_lie)["status"], "FAIL")
        self.assertIn("review_missing_fact", codes(one(with_lie)))

    def test_wrong_cite_is_fail_and_does_not_widen(self):
        body = (
            '[Ch. 2] "A watermark is a threshold used to track the progress of a stream."\n'
            "A watermark tracks how far a stream has advanced."
        )
        report = RE.evaluate([golden()], [response(body)], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("quote_outside_cited_chapter", codes(one(report)))

    def test_forged_quote_is_fail(self):
        body = (
            '[Ch. 8] "A watermark is the capital of France and also a small moon."\n'
            "The book does not say that."
        )
        report = RE.evaluate([golden()], [response(body)], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("quote_not_in_shown_evidence", codes(one(report)))

    # -- quote attribution is structural, never a length threshold ---------
    # Independent review 2026-10-29, finding 3: a tagged quote under 20
    # characters was invisible while an untagged scare quote over 20 was
    # failed. Attribution now comes from the [Ch. ...] tag (or an explicit
    # structured citation quote), so both directions are checked.

    def test_short_tagged_forged_quote_fails_with_a_fresh_review(self):
        g = golden()
        baseline = response(GOOD_BODY)
        baseline_record = one(RE.evaluate([g], [baseline], [review(g, baseline)], self_check=False))
        self.assertEqual(baseline_record["status"], "PASS")

        forged = response(GOOD_BODY + '\n[Ch. 8] "capital of France"')
        record = one(RE.evaluate([g], [forged], [review(g, forged)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertEqual(record["status"], "FAIL", record)
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_short_verbatim_book_quote_is_checked_and_accepted(self):
        short = "Streams flow."
        g = golden()
        r = response(
            f'[Ch. 8 chunk_id=ch08-041] "{short}"\n'
            "A watermark tracks how far the incoming records have advanced.",
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-041", "ch08-041", "8", f"{short} A watermark tracks progress."),
                ],
            },
        )
        record = one(RE.evaluate([g], [r], [review(g, r)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
        self.assertEqual(record["status"], "PASS", record)

    def test_unattributed_scare_quote_is_not_a_book_claim(self):
        g = golden()
        body = (
            GOOD_BODY
            + '\nIn plain words, a watermark is not "a clock that resets nightly" but a moving mark.'
        )
        r = response(body)
        without_review = one(RE.evaluate([g], [r], self_check=False))
        self.assertEqual(without_review["mechanical"]["status"], "PASS", without_review["causes"])
        self.assertEqual(without_review["semantic"]["status"], "REVIEW")
        self.assertEqual(without_review["status"], "REVIEW")

        with_review = one(RE.evaluate([g], [r], [review(g, r)], self_check=False))
        self.assertEqual(with_review["status"], "PASS", with_review)
        self.assertNotIn("quote_not_in_shown_evidence", codes(with_review))

    def test_long_unattributed_scare_quote_is_still_not_a_book_claim(self):
        g = golden()
        body = (
            GOOD_BODY
            + '\nThe phrase "a threshold that only exists inside the second paragraph of a '
            'different book" describes how it feels, not what the book says.'
        )
        r = response(body)
        record = one(RE.evaluate([g], [r], [review(g, r)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
        self.assertEqual(record["status"], "PASS", record)

    def test_unattributed_verbatim_book_quote_is_review_not_ignored(self):
        g = golden()
        body = (
            GOOD_BODY
            + '\nThe book calls it "A watermark is a threshold used to track the progress of a stream."'
        )
        r = response(body)
        record = one(RE.evaluate([g], [r], [review(g, r)], self_check=False))
        self.assertIn("quote_untagged", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")

    def test_curly_tagged_forged_quote_fails(self):
        body = GOOD_BODY + "\n[Ch. 8] “capital of France”"
        record = one(RE.evaluate([golden()], [response(body)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_every_tagged_quote_is_checked_not_only_the_first(self):
        body = (
            '[Ch. 8] "capital of France" and [Ch. 8] "a small moon made of cheese"\n'
            "A watermark tracks how far the incoming records have advanced."
        )
        record = one(RE.evaluate([golden()], [response(body)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "FAIL")
        findings = [f for f in record["findings"] if f["code"] == "quote_not_in_shown_evidence"]
        self.assertEqual(len(findings), 2, record["findings"])

    def test_unclosed_tagged_quote_is_review_not_ignored(self):
        body = GOOD_BODY + '\n[Ch. 8] "capital of France'
        record = one(RE.evaluate([golden()], [response(body)], self_check=False))
        self.assertIn("quote_unclosed", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")

    def test_wrapped_tagged_quote_is_folded_review_not_ignored(self):
        body = (
            '[Ch. 8] "A watermark is a threshold used to\n'
            'track the progress of a stream."\n'
            "A watermark tracks how far the incoming records have advanced."
        )
        record = one(RE.evaluate([golden()], [response(body)], self_check=False))
        self.assertIn("quote_folded_only", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")

    def test_structured_citation_quote_is_checked_against_its_chunk(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        r = response(
            PARAPHRASE,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-040", "quote": "capital of France"}]
        record = one(RE.evaluate([g], [r], stage="system", self_check=False), stage="system")
        self.assertEqual(record["status"], "FAIL", record)
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_quote_is_checked_only_against_actually_shown_evidence(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-042", "ch08-042", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-042"],
        )
        body = '[Ch. 8] "Schema evolution changes a table."\nA watermark tracks progress.'
        record = one(RE.evaluate([g], [response(body)], self_check=False))
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_quote_after_prose_on_the_same_line_is_ambiguous_review(self):
        body = GOOD_BODY + '\n[Ch. 8] The book calls it "capital of France".'
        record = one(RE.evaluate([golden()], [response(body)], self_check=False))
        self.assertIn("quote_attribution_ambiguous", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")

    def test_structured_citation_quote_is_bound_to_the_review(self):
        g = golden()
        r = response(
            PARAPHRASE,
            evidence={"status": "shown", "sources": [shown("fde:ch08-039", "ch08-039", "8", S1)]},
        )
        r["reader"]["citations"] = [
            {"chapter": "8", "chunk_id": "ch08-039", "quote": "A watermark is a threshold"}
        ]
        rev = review(g, r, stage="system")
        first = one(RE.evaluate([g], [r], [rev], stage="system", self_check=False), stage="system")
        self.assertEqual(first["status"], "PASS", first)

        changed = copy.deepcopy(r)
        changed["reader"]["citations"][0]["quote"] = "It moves with the data."
        second = one(
            RE.evaluate([g], [changed], [rev], stage="system", self_check=False), stage="system"
        )
        self.assertEqual(second["status"], "REVIEW")
        self.assertIn("review_stale_citation", codes(second))

    def test_prior_criterion_version_is_not_retroactively_certified(self):
        g = golden()
        r = response(PARAPHRASE)
        rev = review(g, r)
        self.assertEqual(RE.EVALUATOR["criterion_version"], "reviewed-semantics-v2")
        rev["bind"]["criterion_version"] = "reviewed-semantics-v1"
        record = one(RE.evaluate([g], [r], [rev], self_check=False))
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_criterion", codes(record))

    # -- engine query disclosures are metadata, not book quotations --------
    # Actual baseline 2026-10-29: the engine appends `Asked as: "..."` (or
    # `Read as: "..."`) to the reader text. At system stage with exactly one
    # structured citation, the old fallback attached that question echo to the
    # citation and failed it as an invented book quote. The disclosure is not
    # a claim about the book; tagged and explicitly-quoted claims still are.

    def test_system_asked_as_disclosure_is_not_a_book_quote(self):
        g = golden(task_stage="system")
        baseline = response(GOOD_BODY)
        baseline_record = one(
            RE.evaluate(
                [g], [baseline], [review(g, baseline, stage="system")],
                stage="system", self_check=False,
            ),
            stage="system",
        )
        self.assertEqual(baseline_record["status"], "PASS", baseline_record)

        disclosed = response(GOOD_BODY + '\nAsked as: "What is a watermark?"')
        record = one(
            RE.evaluate(
                [g], [disclosed], [review(g, disclosed, stage="system")],
                stage="system", self_check=False,
            ),
            stage="system",
        )
        self.assertEqual(record["mechanical"]["status"], "PASS", record["causes"])
        self.assertEqual(record["status"], "PASS", record)
        self.assertIn("engine_disclosure_skipped:1", record["notes"])

    def test_system_read_as_disclosure_is_not_a_book_quote(self):
        g = golden(task_stage="system")
        r = response(GOOD_BODY + '\nRead as: "watermark"')
        record = one(
            RE.evaluate([g], [r], [review(g, r, stage="system")], stage="system", self_check=False),
            stage="system",
        )
        self.assertEqual(record["status"], "PASS", record)
        self.assertIn("engine_disclosure_skipped:1", record["notes"])

    def test_system_scare_quote_with_one_citation_does_not_fail_mechanics(self):
        g = golden(task_stage="system")
        body = GOOD_BODY + '\nIn plain words, it is not "a clock that resets nightly" but a moving mark.'
        r = response(body)
        unreviewed = one(RE.evaluate([g], [r], stage="system", self_check=False), stage="system")
        self.assertEqual(unreviewed["mechanical"]["status"], "PASS", unreviewed["causes"])
        self.assertEqual(unreviewed["status"], "REVIEW")
        reviewed = one(
            RE.evaluate([g], [r], [review(g, r, stage="system")], stage="system", self_check=False),
            stage="system",
        )
        self.assertEqual(reviewed["status"], "PASS", reviewed)
        self.assertNotIn("quote_not_in_shown_evidence", codes(reviewed))

    def test_system_tagged_forgery_still_fails_with_one_citation(self):
        g = golden(task_stage="system")
        r = response(GOOD_BODY + '\n[Ch. 8] "capital of France"')
        record = one(
            RE.evaluate([g], [r], [review(g, r, stage="system")], stage="system", self_check=False),
            stage="system",
        )
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_system_disclosure_line_cannot_hide_a_tagged_forgery(self):
        g = golden(task_stage="system")
        r = response(GOOD_BODY + '\nAsked as: "What is a watermark?" [Ch. 8] "capital of France"')
        record = one(RE.evaluate([g], [r], stage="system", self_check=False), stage="system")
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_system_bare_book_quote_with_one_citation_is_review(self):
        g = golden(task_stage="system")
        r = response(
            '"A watermark is a threshold used to track the progress of a stream."\n'
            "A watermark tracks how far the incoming records have advanced."
        )
        record = one(
            RE.evaluate([g], [r], [review(g, r, stage="system")], stage="system", self_check=False),
            stage="system",
        )
        self.assertIn("quote_untagged", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")
        self.assertEqual(record["status"], "REVIEW")

    def test_system_disclosure_does_not_skip_a_structured_quote_claim(self):
        g = golden(
            task_stage="system",
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        r = response(
            PARAPHRASE + '\nAsked as: "What is a watermark?"',
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-040", "quote": "capital of France"}]
        record = one(RE.evaluate([g], [r], stage="system", self_check=False), stage="system")
        self.assertEqual(record["mechanical"]["status"], "FAIL", record["causes"])
        self.assertIn("quote_not_in_shown_evidence", codes(record))

    def test_system_unclosed_book_claim_is_review_not_ignored(self):
        g = golden(task_stage="system")
        r = response(GOOD_BODY + '\n[Ch. 8] "capital of France')
        record = one(RE.evaluate([g], [r], stage="system", self_check=False), stage="system")
        self.assertIn("quote_unclosed", codes(record))
        self.assertEqual(record["mechanical"]["status"], "REVIEW")

    def test_disclosure_is_kept_in_the_output_binding(self):
        g = golden(task_stage="system")
        body = GOOD_BODY + '\nAsked as: "What is a watermark?"'
        r = response(body)
        before = copy.deepcopy(r)
        record = one(
            RE.evaluate([g], [r], [review(g, r, stage="system")], stage="system", self_check=False),
            stage="system",
        )
        self.assertEqual(record["binding"]["output_sha256"], digest(body))
        self.assertEqual(r, before)

    def test_same_bytes_model_stage_has_no_engine_disclosure_exemption(self):
        # One response, one set of bytes: the raw model body and the engine
        # reader text are identical. Only the graded stage (and the block's
        # provenance) differs. A raw model line must not borrow the engine's
        # metadata exemption; the engine's own line must keep it.
        verbatim = "A watermark is a threshold used to track the progress of a stream."
        g = golden()  # no task_stage: neither stage is capped by a mismatch
        for label in ("Asked as:", "Read as:"):
            body = GOOD_BODY + f'\n{label} "{verbatim}"'
            r = response(body)
            self.assertEqual(r["model"]["provenance"], "model")
            self.assertEqual(r["reader"]["provenance"], "engine")
            self.assertEqual(r["model"]["raw_body"], r["reader"]["final_text"])

            model_record = one(
                RE.evaluate([g], [r], [review(g, r)], stage="model", self_check=False),
                stage="model",
            )
            self.assertEqual(model_record["mechanical"]["status"], "REVIEW", model_record["causes"])
            self.assertIn("quote_untagged", codes(model_record))
            self.assertEqual(model_record["status"], "REVIEW")
            self.assertNotIn("engine_disclosure_skipped:1", model_record["notes"])

            system_record = one(
                RE.evaluate(
                    [g], [r], [review(g, r, stage="system")],
                    stage="system", self_check=False,
                ),
                stage="system",
            )
            self.assertEqual(system_record["mechanical"]["status"], "PASS", system_record["causes"])
            self.assertEqual(system_record["status"], "PASS", system_record)
            self.assertIn("engine_disclosure_skipped:1", system_record["notes"])

    def test_system_disclosure_requires_engine_reader_provenance(self):
        # Same SYSTEM bytes, same stage: only the reader's declared provenance
        # changes. Engine/mixed may be metadata; an explicit model reader text
        # is a model claim, and missing provenance stays readiness REVIEW
        # without inventing an engine authorship or a quote FAIL.
        verbatim = "A watermark is a threshold used to track the progress of a stream."
        g = golden()  # no task_stage: neither stage is capped by a mismatch
        for label in ("Asked as:", "Read as:"):
            body = GOOD_BODY + f'\n{label} "{verbatim}"'

            model_input = response(body)
            model_record = one(
                RE.evaluate([g], [model_input], [review(g, model_input)], stage="model", self_check=False),
                stage="model",
            )
            self.assertEqual(model_record["mechanical"]["status"], "REVIEW", model_record["causes"])
            self.assertIn("quote_untagged", codes(model_record))
            self.assertEqual(model_record["status"], "REVIEW")

            engine = response(body)
            engine["reader"]["provenance"] = "engine"
            engine_record = one(
                RE.evaluate([g], [engine], [review(g, engine, stage="system")], stage="system", self_check=False),
                stage="system",
            )
            self.assertEqual(engine_record["mechanical"]["status"], "PASS", engine_record["causes"])
            self.assertEqual(engine_record["status"], "PASS", engine_record)
            self.assertIn("engine_disclosure_skipped:1", engine_record["notes"])

            model_reader = response(body)
            model_reader["reader"]["provenance"] = "model"
            model_reader_record = one(
                RE.evaluate(
                    [g], [model_reader], [review(g, model_reader, stage="system")],
                    stage="system", self_check=False,
                ),
                stage="system",
            )
            self.assertEqual(
                model_reader_record["mechanical"]["status"], "REVIEW", model_reader_record["causes"]
            )
            self.assertIn("quote_untagged", codes(model_reader_record))
            self.assertEqual(model_reader_record["status"], "REVIEW")
            self.assertNotIn("engine_disclosure_skipped:1", model_reader_record["notes"])

            missing = response(GOOD_BODY + f'\n{label} "What is a watermark?"')
            missing["reader"]["provenance"] = None
            missing_record = one(
                RE.evaluate(
                    [g], [missing], [review(g, missing, stage="system")],
                    stage="system", self_check=False,
                ),
                stage="system",
            )
            self.assertIn("reader_provenance_missing", codes(missing_record))
            self.assertEqual(missing_record["mechanical"]["status"], "REVIEW", missing_record["causes"])
            self.assertNotIn("quote_not_in_shown_evidence", codes(missing_record))
            self.assertEqual(missing_record["status"], "REVIEW")
            self.assertNotIn("engine_disclosure_skipped:1", missing_record["notes"])

    def test_refuse_all_fails_an_answerable_item(self):
        report = RE.evaluate([golden()], [response("Not in this book.")], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("false_refusal", codes(one(report)))

    def test_missing_valid_refusal_fails_a_refusal_item(self):
        g = golden(
            id="g-refuse",
            family_id="capital",
            question="What is the capital of France?",
            provided_source_ids=[],
            expected={
                "book_answerable": False,
                "evidence_sufficient": False,
                "allowed_behaviors": ["refuse"],
                "required_facts": [],
                "unsupported_claims": [],
            },
            target_kind="refusal",
        )
        r = response(
            "Paris is the capital of France.",
            golden_id="g-refuse",
            evidence={"status": "shown", "sources": []},
        )
        report = RE.evaluate([g], [r], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("answer_when_refusal_expected", codes(one(report)))

    def test_quote_only_is_fail(self):
        body = '[Ch. 8] "A watermark is a threshold used to track the progress of a stream."'
        report = RE.evaluate([golden()], [response(body)], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("quote_only_no_explanation", codes(one(report)))

    def test_answer_without_citation_is_review_even_with_a_review(self):
        g = golden()
        r = response("It keeps count of how far the incoming records have advanced.")
        report = RE.evaluate([g], [r], [review(g, r)], self_check=False)
        self.assertEqual(one(report)["status"], "REVIEW")
        self.assertIn("answer_uncited", codes(one(report)))

    # -- positive control: a true paraphrase with an independent review -----

    def test_valid_paraphrase_with_source_backed_review_passes(self):
        g = golden()
        r = response(PARAPHRASE)
        report = RE.evaluate([g], [r], [review(g, r)], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "PASS", record)
        self.assertEqual(record["mechanical"]["status"], "PASS")
        self.assertEqual(record["semantic"]["status"], "PASS")
        self.assertEqual(record["outcome_class"], "reviewed_pass")
        # The answer shares little wording with the fact; the review, not a
        # keyword match, is what lets this pass.
        self.assertNotIn("threshold used to track", PARAPHRASE)

    def test_gloss_only_may_quote_without_a_tag(self):
        g = golden()
        g["target_kind"] = "gloss"
        g["review"]["content_sha256"] = RE.content_digest(g)
        body = (
            '"A watermark is a threshold used to track the progress of a stream." '
            "It marks how far the incoming records have advanced."
        )
        r = response(body)
        report = RE.evaluate([g], [r], [review(g, r)], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "PASS", record)
        self.assertIn("quote_untagged_gloss", record["notes"])

    # -- review validity ----------------------------------------------------

    def test_uncertain_entailment_is_review_and_visible(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(
            g,
            r,
            facts=[{"fact_index": 0, "status": "uncertain", "witness": None}],
            ambiguity="The gloss could be read as tracking bytes rather than progress.",
        )
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_fact_uncertain", codes(record))
        self.assertTrue(record["ambiguity"])

    def test_missing_evidence_is_review_not_model_fail(self):
        g = golden()
        r = response(GOOD_BODY, evidence={"status": "missing", "sources": []})
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("evidence_unverifiable", codes(record))
        self.assertNotEqual(record["subject"], "model")

    def test_modified_response_invalidates_review(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        r["model"]["raw_body"] += " One more sentence that was not reviewed."
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_output", codes(record))

    def test_modified_evidence_invalidates_review(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        r["evidence"]["sources"][0]["text"] += " A sentence added after review."
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_evidence", codes(record))

    def test_modified_question_invalidates_review(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        r["input"]["question"] = "What is a watermark, exactly?"
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_input", codes(record))

    def test_model_change_invalidates_review(self):
        g = golden()
        r = response(PARAPHRASE)
        rev = review(g, r)
        r["model"]["digest"] = "def456"
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_model", codes(record))

    def test_modified_citation_invalidates_review(self):
        g = golden()
        r = response(PARAPHRASE)
        r["reader"]["final_text"] = PARAPHRASE
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-039"}]
        rev = review(g, r, stage="system")
        r["reader"]["citations"] = [{"chapter": "2", "chunk_id": "ch02-022"}]
        report = RE.evaluate([g], [r], [rev], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_citation", codes(record))

    def test_transport_error_with_a_review_stays_unverifiable(self):
        g = golden()
        r = response(GOOD_BODY, capture={"status": "transport_error", "error": "reset"})
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_unverifiable", codes(record))
        self.assertNotIn("FAIL", {finding["verdict"] for finding in record["findings"]})

    def test_modified_reference_invalidates_review(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        changed = copy.deepcopy(g)
        changed["expected"]["required_facts"][0]["claim"] = "A watermark is a wall clock."
        report = RE.evaluate([changed], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_reference", codes(record))

    def test_old_reference_and_criterion_versions_are_stale(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        rev["bind"]["reference_version"] = "golden-v0"
        report = RE.evaluate([g], [r], [rev], self_check=False)
        self.assertIn("review_stale_reference", codes(one(report)))

        rev = review(g, r)
        rev["bind"]["criterion_version"] = "go-judge-v3"
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("review_stale_criterion", codes(record))

    def test_known_bad_review_fails(self):
        g = golden()
        r = response(GOOD_BODY)
        bad_witness = review(g, r)
        bad_witness["facts"][0]["witness"]["quote"] = "A watermark is a magical force."
        report = RE.evaluate([g], [r], [bad_witness], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("review_witness_quote_invalid", codes(one(report)))

        hidden = review(g, r)
        hidden["facts"][0]["witness"]["source_id"] = "fde:ch01-001"
        report = RE.evaluate([g], [r], [hidden], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("review_witness_source_not_shown", codes(one(report)))

        failed = review(g, r, verdict="fail")
        report = RE.evaluate([g], [r], [failed], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("review_failed", codes(one(report)))

    def test_review_for_another_stage_is_not_reused(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r, stage="model")
        report = RE.evaluate([g], [r], [rev], stage="both", self_check=False)
        self.assertEqual(one(report, stage="model")["status"], "PASS")
        self.assertEqual(one(report, stage="system")["status"], "REVIEW")
        self.assertIn("review_missing", codes(one(report, stage="system")))

    def test_pending_golden_cannot_pass(self):
        g = golden()
        g["review"]["status"] = "needs_review"
        r = response(PARAPHRASE)
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("golden_unreviewed", codes(record))
        self.assertEqual(record["readiness"]["status"], "REVIEW")
        self.assertTrue(record["ambiguity"])

    def test_forged_golden_content_hash_cannot_pass(self):
        g = golden()
        g["review"]["content_sha256"] = "0" * 64
        r = response(PARAPHRASE)
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("golden_review_stale_content", codes(record))

    def test_utility_false_means_the_quote_did_not_answer(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        rev["utility"]["answers_question"] = False
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("review_utility_failed", codes(record))

    def test_forged_capture_hashes_cannot_pass(self):
        g = golden()
        for label, mutate in (
            ("model", lambda r: r["model"].__setitem__("output_sha256", "0" * 64)),
            ("evidence", lambda r: r["evidence"].__setitem__("evidence_sha256", "0" * 64)),
            ("input", lambda r: r["input"].__setitem__("input_sha256", "0" * 64)),
        ):
            with self.subTest(label=label):
                r = response(PARAPHRASE)
                rev = review(g, r)
                mutate(r)
                report = RE.evaluate([g], [r], [rev], self_check=False)
                record = one(report)
                self.assertEqual(record["status"], "REVIEW", record["causes"])
                self.assertIn(
                    {"model": "capture_hash_mismatch", "evidence": "evidence_hash_mismatch", "input": "input_hash_mismatch"}[label],
                    codes(record),
                )

    def test_review_behavior_contradiction_fails(self):
        g = golden()
        r = response("Not in this book.")
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("review_behavior_contradiction", codes(record))

    def test_support_mode_all_needs_every_witness(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        g["expected"]["required_facts"] = [
            {
                "claim": FACT,
                "source_ids": ["fde:ch08-039", "fde:ch08-040"],
                "support_mode": "all",
            }
        ]
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response(
            PARAPHRASE,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("review_fact_unwitnessed", codes(record))

    def test_alternative_shown_source_can_witness_a_fact(self):
        g = golden()
        r = response(
            PARAPHRASE,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-041", "ch08-041", "8", S1),
                ],
            },
        )
        rev = review(g, r)
        rev["facts"][0]["witness"]["source_id"] = "fde:ch08-041"
        report = RE.evaluate([g], [r], [rev], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "PASS", record)
        self.assertIn("alternative_witness", record["notes"])

    def test_engine_chunk_citation_is_narrow(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        r = response(
            GOOD_BODY,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-040"}]
        report = RE.evaluate([g], [r], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("quote_not_in_cited_chunk", codes(record))
        self.assertEqual(record["subject"], "engine")

    def test_unreadable_rows_are_counted_not_dropped(self):
        bad_golden = {"__unreadable__": "not json", "__line__": 2}
        report = RE.evaluate([bad_golden], [response()], self_check=False)
        self.assertIn("golden_unreadable", {code for rec in report["records"] for code in rec["causes"]})
        self.assertEqual(report["counts"]["outputs_total"], 2)
        self.assertEqual(report["counts"]["goldens_invalid"], 1)

        bad_response = {"__unreadable__": "not json", "__line__": 3}
        report = RE.evaluate([golden()], [bad_response], self_check=False)
        self.assertIn("response_unreadable", {code for rec in report["records"] for code in rec["causes"]})
        self.assertEqual(report["counts"]["outputs_total"], 2)

    # -- citation and quote mechanics --------------------------------------

    def test_chapter_only_ambiguity_is_not_called_wrong(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        r = response(
            GOOD_BODY,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["mechanical"]["status"], "PASS")
        self.assertFalse(any(code.startswith("quote_outside") for code in codes(record)))
        self.assertIn("chapter_only_ambiguous", record["notes"])

    def test_explicit_chunk_citation_is_narrow(self):
        g = golden(
            source_refs=[
                ref("fde:ch08-039", "ch08-039", "8", S1),
                ref("fde:ch08-040", "ch08-040", "8", S3),
            ],
            provided_source_ids=["fde:ch08-039", "fde:ch08-040"],
        )
        body = (
            '[Ch. 8 chunk_id=ch08-040] "A watermark is a threshold used to track the progress of a stream."\n'
            "A watermark tracks progress."
        )
        r = response(
            body,
            evidence={
                "status": "shown",
                "sources": [
                    shown("fde:ch08-039", "ch08-039", "8", S1),
                    shown("fde:ch08-040", "ch08-040", "8", S3),
                ],
            },
        )
        report = RE.evaluate([g], [r], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("quote_not_in_cited_chunk", codes(one(report)))

    def test_citation_target_is_checked_even_without_a_quote(self):
        body = (
            "[Ch. 8 chunk_id=ch08-999] It keeps count of how far the incoming "
            "records have advanced."
        )
        report = RE.evaluate([golden()], [response(body)], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("cited_chunk_not_shown", codes(one(report)))

    def test_engine_structured_citation_not_shown_fails(self):
        g = golden()
        r = response(PARAPHRASE)
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-999"}]
        report = RE.evaluate([g], [r], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("cited_chunk_not_shown", codes(record))
        self.assertEqual(record["subject"], "engine")

    def test_folded_quote_is_review_not_pass(self):
        body = (
            '[Ch. 8] "a watermark is a threshold used to track the progress of a stream."\n'
            "A watermark tracks progress."
        )
        report = RE.evaluate([golden()], [response(body)], self_check=False)
        record = one(report)
        self.assertNotEqual(record["status"], "PASS")
        self.assertIn("quote_folded_only", codes(record))

    def test_refusal_with_commentary_is_fail(self):
        g = golden(
            id="g-refuse",
            family_id="capital",
            question="What is the capital of France?",
            provided_source_ids=[],
            expected={
                "book_answerable": False,
                "evidence_sufficient": False,
                "allowed_behaviors": ["refuse"],
                "required_facts": [],
                "unsupported_claims": [],
            },
            target_kind="refusal",
        )
        r = response(
            "Not in this book. However, Paris is the capital of France.",
            golden_id="g-refuse",
            evidence={"status": "shown", "sources": []},
        )
        report = RE.evaluate([g], [r], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("refusal_not_exact", codes(one(report)))

    # -- attribution and context -------------------------------------------

    def test_length_stop_is_a_real_fail_not_an_invalid_run(self):
        r = response(
            '[Ch. 8] "A watermark is a threshold used to track the progress of'
        )
        r["model"]["done_reason"] = "length"
        report = RE.evaluate([golden()], [r])
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("output_truncated_length_stop", codes(record))
        self.assertEqual(report["counts"]["length_stop_failures"], 1)
        self.assertTrue(report["valid"])

    def test_transport_error_is_unverifiable_not_a_model_fail(self):
        r = response(GOOD_BODY, capture={"status": "transport_error", "error": "connection reset"})
        report = RE.evaluate([golden()], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("unverifiable_transport", codes(record))
        self.assertEqual(report["counts"]["unverifiable"], 1)
        self.assertNotEqual(record["subject"], "model")

    def test_model_stage_never_falls_back_to_reader_output(self):
        g = golden()
        r = response("What is a watermark?")
        r["reader"]["final_text"] = GOOD_BODY
        r["reader"]["citations"] = [{"chapter": "8", "chunk_id": "ch08-039"}]
        report = RE.evaluate([g], [r], stage="both", self_check=False)
        self.assertEqual(one(report, stage="model")["status"], "FAIL")
        self.assertIn("echo_not_an_answer", codes(one(report, stage="model")))
        self.assertNotEqual(one(report, stage="system")["status"], "FAIL")

    def test_system_stage_scores_reader_output_and_marks_code_fallback(self):
        g = golden()
        r = response("What is a watermark?")
        r["reader"]["final_text"] = GOOD_BODY
        r["reader"]["code_fallback"] = True
        rev = review(g, r, stage="system")
        report = RE.evaluate([g], [r], [rev], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "PASS", record)
        self.assertIn("code_fallback_present", record["notes"])
        self.assertEqual(record["subject"], "system")

    def test_model_refusal_with_insufficient_actual_evidence_is_legitimate(self):
        g = golden()
        r = response(
            "Not in this book.",
            evidence={"status": "shown", "sources": [shown("fde:ch02-022", "ch02-022", "2", S2)]},
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "PASS", record)
        self.assertEqual(record["outcome_class"], "model_refusal_legitimate_insufficient_context")
        self.assertEqual(report["counts"]["model_context_insufficient"], 1)

    def test_allowed_refusal_with_withheld_evidence_is_counted_separately(self):
        g = golden()
        g["expected"]["evidence_sufficient"] = False
        g["expected"]["allowed_behaviors"] = ["refuse"]
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response(
            "Not in this book.",
            evidence={"status": "shown", "sources": [shown("fde:ch02-022", "ch02-022", "2", S2)]},
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "PASS", record)
        self.assertEqual(record["outcome_class"], "model_refusal_legitimate_withheld_evidence")
        self.assertEqual(report["counts"]["model_refusal_withheld"], 1)

    def test_refusal_with_actual_sufficient_evidence_and_a_stale_flag_is_not_pass(self):
        g = golden()
        g["expected"]["evidence_sufficient"] = False
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response("Not in this book.")
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("golden_evidence_flag_stale", codes(record))
        self.assertNotEqual(record["outcome_class"], "model_refusal_legitimate_withheld_evidence")

    def test_system_refusal_with_sufficient_actual_evidence_is_generation_even_if_flag_false(self):
        g = golden()
        g["expected"]["evidence_sufficient"] = False
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response("Not in this book.")
        report = RE.evaluate([g], [r], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("false_refusal_generation", codes(record))

    def test_boundary_behavior_needs_review_and_permission(self):
        g = golden()
        g["expected"]["allowed_behaviors"] = ["answer", "boundary"]
        g["review"]["content_sha256"] = RE.content_digest(g)
        r = response(PARAPHRASE)
        rev = review(g, r, behavior="boundary")
        report = RE.evaluate([g], [r], [rev], self_check=False)
        self.assertEqual(one(report)["status"], "PASS")

        g2 = golden()
        g2["review"]["content_sha256"] = RE.content_digest(g2)
        r2 = response(PARAPHRASE)
        rev2 = review(g2, r2, behavior="boundary")
        report = RE.evaluate([g2], [r2], [rev2], self_check=False)
        self.assertEqual(one(report)["status"], "FAIL")
        self.assertIn("review_behavior_not_allowed", codes(one(report)))

    def test_system_refusal_with_insufficient_actual_evidence_is_retrieval_miss(self):
        g = golden()
        r = response(
            "Not in this book.",
            evidence={"status": "shown", "sources": [shown("fde:ch02-022", "ch02-022", "2", S2)]},
        )
        report = RE.evaluate([g], [r], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("system_retrieval_miss", codes(record))
        self.assertEqual(record["subject"], "engine")
        self.assertEqual(report["counts"]["system_retrieval_misses"], 1)

    def test_system_false_refusal_with_sufficient_evidence_is_generation_failure(self):
        g = golden()
        r = response("Not in this book.")
        report = RE.evaluate([g], [r], stage="system", self_check=False)
        record = one(report, stage="system")
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("false_refusal_generation", codes(record))

    def test_guard_false_refusal_is_attributed_to_the_engine(self):
        g = golden()
        r = response(
            "Not in this book.",
            capture={"status": "no_call"},
            evidence={"status": "guard_no_call", "sources": []},
        )
        report = RE.evaluate([g], [r], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "FAIL")
        self.assertIn("guard_false_refusal", codes(record))
        self.assertEqual(record["subject"], "engine")

    def test_model_output_without_model_provenance_is_unverifiable(self):
        g = golden()
        r = response(GOOD_BODY)
        r["model"]["provenance"] = "code"
        report = RE.evaluate([g], [r], [review(g, r)], self_check=False)
        record = one(report)
        self.assertEqual(record["status"], "REVIEW")
        self.assertIn("model_output_not_model", codes(record))

    # -- coverage, skips, and records --------------------------------------

    def test_missing_response_is_counted_not_skipped(self):
        g1 = golden()
        g2 = golden(id="g-watermark-2", family_id="watermark-2")
        report = RE.evaluate([g1, g2], [response()], self_check=False)
        self.assertEqual(report["counts"]["outputs_total"], 2)
        missing = [rec for rec in report["records"] if rec.get("golden_id") == "g-watermark-2"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["status"], "REVIEW")
        self.assertIn("response_missing", codes(missing[0]))

    def test_response_for_unknown_golden_is_visible(self):
        r = response(golden_id="g-not-in-file")
        report = RE.evaluate([golden()], [r], self_check=False)
        self.assertTrue(any("golden_unknown" in codes(rec) for rec in report["records"]))
        self.assertEqual(report["counts"]["outputs_total"], 2)

    def test_duplicate_and_orphan_reviews_are_visible(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        report = RE.evaluate([g], [r], [rev, copy.deepcopy(rev)], self_check=False)
        self.assertIn("review_duplicate", codes(one(report)))
        self.assertEqual(one(report)["status"], "REVIEW")

        orphan = review(g, r, response_id="r-not-here")
        report = RE.evaluate([g], [r], [orphan], self_check=False)
        self.assertEqual(report["counts"]["reviews"]["orphan"], 1)
        self.assertIn("review_missing", codes(one(report)))

    def test_unreadable_review_is_not_clean(self):
        report = RE.evaluate(
            [golden()],
            [response(PARAPHRASE)],
            [{"__unreadable__": "not json", "__line__": 1}],
            self_check=False,
        )
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertIn("review_unreadable", {finding["code"] for finding in report["findings"]})

    def test_inputs_are_not_mutated(self):
        g = golden()
        r = response(GOOD_BODY)
        rev = review(g, r)
        before = copy.deepcopy((g, r, rev))
        RE.evaluate([g], [r], [rev], self_check=False)
        self.assertEqual((g, r, rev), before)

    # -- self-check controls and CLI ---------------------------------------

    def test_self_check_has_a_passing_positive_and_no_passing_negative(self):
        controls = RE.self_check()
        self.assertTrue(controls["valid"], controls)
        self.assertEqual(controls["controls"]["paraphrase_positive"]["status"], "PASS")
        negatives = [name for name in controls["controls"] if name != "paraphrase_positive"]
        self.assertTrue(negatives)
        for name in negatives:
            self.assertNotEqual(
                controls["controls"][name]["status"], "PASS", f"control {name} passed"
            )
        statuses = {controls["controls"][name]["status"] for name in negatives}
        self.assertIn("FAIL", statuses)
        self.assertIn("REVIEW", statuses)

    def test_cli_exit_codes_and_out_is_never_overwritten(self):
        g = golden()
        r = response(PARAPHRASE)
        rev = review(g, r)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            golden_path = tmp / "goldens.jsonl"
            responses_path = tmp / "responses.jsonl"
            reviews_path = tmp / "reviews.jsonl"
            golden_path.write_text(json.dumps(g) + "\n", encoding="utf-8")
            responses_path.write_text(json.dumps(r) + "\n", encoding="utf-8")
            reviews_path.write_text(json.dumps(rev) + "\n", encoding="utf-8")
            out_path = tmp / "report.json"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = RE.main(
                    [
                        "--golden",
                        str(golden_path),
                        "--responses",
                        str(responses_path),
                        "--reviews",
                        str(reviews_path),
                        "--stage",
                        "model",
                        "--json",
                        "--out",
                        str(out_path),
                    ]
                )
            self.assertEqual(code, 0, stream.getvalue())
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(report["verdict"], "PASS")
            original = out_path.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                again = RE.main(
                    [
                        "--golden",
                        str(golden_path),
                        "--responses",
                        str(responses_path),
                        "--reviews",
                        str(reviews_path),
                        "--stage",
                        "model",
                        "--out",
                        str(out_path),
                    ]
                )
            self.assertEqual(again, 2)
            self.assertEqual(out_path.read_bytes(), original)

            responses_path.write_text(json.dumps(response("What is a watermark?")) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                fail_code = RE.main(
                    [
                        "--golden",
                        str(golden_path),
                        "--responses",
                        str(responses_path),
                        "--stage",
                        "model",
                        "--json",
                    ]
                )
            self.assertEqual(fail_code, 2)


if __name__ == "__main__":
    unittest.main()
