"""Dataset integrity: the data errors that make a golden or an eval meaningless.

Each case below is a failure class seen or paid for in this repo: quotes that
exist nowhere in the book, chapters that moved after a re-chunk, gold that was
never shown to the model, families split across train and test, and a "clean"
leakage result produced without ever reading the training corpus.

All fixtures are synthetic (a three-chunk index, one caption, a synthetic
domain) so the suite runs on a machine without `data/`. Nothing here calls a
model.

Contract: `artifacts/runs/data-repair-2026-10-29/validator/SCHEMA.md`.
Module: `artifacts/harnesses/dataset_integrity.py`.
"""

import contextlib
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import dataset_integrity as DI  # noqa: E402

TEXT1 = "A watermark is a threshold used to track the progress of a stream. It moves with the data."
TEXT2 = "Batch processing handles bounded data."
TEXT3 = "Schema evolution changes a table without a rewrite."
CAPTION = "A stream of records arriving over time."
QUOTE = "A watermark is a threshold"
QUOTE_SENTENCE = "A watermark is a threshold used to track the progress of a stream."
TEXT4 = "A stream is a sequence of records that arrives over time."
WRAPPED = "Consistency matters for every reader.\r\nIt refers to a single copy of the data."


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def codes(result):
    return {finding["code"] for finding in result["findings"]}


class Fixture(unittest.TestCase):
    """One synthetic index, one valid record, helpers to break one thing."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="di-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.index_path = self.tmp / "index.demo.json"
        self._write_index(self.index_path)
        self.index_sha = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        self.corpus = self.dataset_file(
            "corpus.jsonl",
            [
                self.record(
                    id="corpus-1",
                    split="train",
                    family_id="corpus-family",
                    question="How does batch processing work?",
                    source_refs=[
                        self.source(
                            chunk_id="ch02-001",
                            chapter="2",
                            text_sha256=digest(TEXT2),
                            spans=[],
                        )
                    ],
                    provided_source_ids=["s1"],
                )
            ],
        )

    def _write_index(self, path, chunks=None, figures=None, book_id="demo"):
        path.write_text(
            json.dumps(
                {
                    "book_id": book_id,
                    "chunks": chunks
                    if chunks is not None
                    else [
                        {"chunk_id": "ch01-001", "chapter": "1", "text": TEXT1},
                        {"chunk_id": "ch01-002", "chapter": "1", "text": TEXT4},
                        {"chunk_id": "ch01-003", "chapter": "1", "text": TEXT1},
                        {"chunk_id": "ch02-001", "chapter": "2", "text": TEXT2},
                        {"chunk_id": "ch02-002", "chapter": "2", "text": WRAPPED},
                        {"chunk_id": "ch03-001", "chapter": "3", "text": TEXT3},
                    ],
                    "figures": figures
                    if figures is not None
                    else [{"id": "figure-2-1", "chapter": "2", "caption": CAPTION}],
                }
            ),
            encoding="utf-8",
        )

    def source(self, **over):
        start = TEXT1.index(QUOTE)
        ref = {
            "source_id": "s1",
            "book_id": "demo",
            "index_path": str(self.index_path),
            "index_sha256": self.index_sha,
            "chunk_id": "ch01-001",
            "chapter": "1",
            "text_sha256": digest(TEXT1),
            "spans": [{"start": start, "end": start + len(QUOTE), "text": QUOTE}],
        }
        ref.update(over)
        return ref

    def caption_source(self, **over):
        start = CAPTION.index("A stream")
        ref = {
            "source_id": "s1",
            "book_id": "demo",
            "index_path": str(self.index_path),
            "index_sha256": self.index_sha,
            "chapter": "2",
            "text_sha256": digest(CAPTION),
            "kind": "caption",
            "figure_id": "figure-2-1",
            "spans": [{"start": start, "end": start + 8, "text": CAPTION[start : start + 8]}],
        }
        ref.update(over)
        return ref

    def record(self, **over):
        rec = {
            "schema_version": 1,
            "id": "demo-001",
            "family_id": "family-a",
            "split": "dev",
            "book_id": "demo",
            "question": "What is a watermark?",
            "history": [],
            "provided_source_ids": ["s1"],
            "source_refs": [self.source()],
            "expected": {
                "book_answerable": True,
                "evidence_sufficient": True,
                "allowed_behaviors": ["answer"],
                "required_facts": [
                    {"claim": "A watermark tracks how far a stream has progressed.", "source_ids": ["s1"]}
                ],
                "unsupported_claims": [],
            },
            "review": {
                "status": "accepted",
                "author": "author-a",
                "reviewer": "reviewer-b",
                "notes": "span checked against ch01-001",
                "provenance": "agent",
            },
            "origin": {
                "path": str(self.index_path),
                "sha256": self.index_sha,
                "record": 1,
                "kind": "authored",
            },
            "target": {
                "kind": "answer",
                "answer": "It marks how far the stream has got.",
                "refused": False,
                "citations": ["s1"],
            },
            "task_stage": "model",
        }
        rec.update(over)
        return self.sign(rec)

    def sign(self, rec):
        """Sign a record exactly as the schema documents (review excluded)."""
        payload = {key: value for key, value in rec.items() if key != "review"}
        rec["review"]["content_sha256"] = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        rec["review"].setdefault("criteria_version", "source-grounding-v1")
        return rec

    def expect(self, rec, **over):
        rec = copy.deepcopy(rec)
        rec["expected"].update(over)
        return self.sign(rec)

    def review(self, rec, **over):
        rec = copy.deepcopy(rec)
        rec["review"].update(over)
        return rec

    def target(self, rec, **over):
        rec = copy.deepcopy(rec)
        rec["target"].update(over)
        return self.sign(rec)

    def check(self, *records, **kwargs):
        kwargs.setdefault("train_corpus", str(self.corpus))
        return DI.check_records([copy.deepcopy(r) for r in records], **kwargs)

    def one(self, *records, **kwargs):
        report = self.check(*records, **kwargs)
        self.assertEqual(len(report["records"]), 1, report["records"])
        return report["records"][0]

    def dataset_file(self, name, records):
        path = self.tmp / name
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        return path


class PassPathTest(Fixture):
    def test_complete_answer_record_passes(self):
        report = self.check(self.record())
        self.assertEqual(report["verdict"], "PASS", report["records"])
        self.assertEqual(report["integrity"]["verdict"], "PASS")
        self.assertEqual(report["lineage"]["status"], "checked")
        self.assertEqual(report["counts"]["records"], 1)
        self.assertEqual(report["counts"]["pass"], 1)
        self.assertEqual(report["counts"]["fail"], 0)

    def test_full_synonym_answer_with_zero_lexical_overlap_passes(self):
        """A correct paraphrase in different words is not a defect.

        Negative controls alone are satisfied by a validator that rejects
        everything; this is the positive control.
        """
        rec = self.target(
            self.record(),
            answer="A travelling mark records how far the flow has advanced.",
        )
        rec = self.expect(
            rec,
            required_facts=[
                {"claim": "A mark records the position the flow has reached.", "source_ids": ["s1"]}
            ],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_gloss_only_training_target_needs_no_citation(self):
        rec = self.target(
            self.record(split="train"),
            kind="gloss",
            answer="A progress marker for a data stream.",
            citations=[],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_caption_source_resolves(self):
        rec = self.record(
            source_refs=[self.caption_source()],
            provided_source_ids=["s1"],
            target={"kind": "gloss", "answer": "Records arrive over time.", "citations": []},
        )
        rec = self.expect(
            rec,
            required_facts=[{"claim": "Records arrive over time.", "source_ids": ["s1"]}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_synthetic_domain_is_legitimate_but_must_declare_itself(self):
        synthetic_index = self.tmp / "index.synthetic.json"
        self._write_index(
            synthetic_index,
            book_id="synthetic-demo",
            chunks=[{"chunk_id": "syn-001", "chapter": "1", "text": TEXT2}],
            figures=[],
        )
        sha = hashlib.sha256(synthetic_index.read_bytes()).hexdigest()
        ref = {
            "source_id": "s1",
            "book_id": "synthetic-demo",
            "index_path": str(synthetic_index),
            "index_sha256": sha,
            "chunk_id": "syn-001",
            "chapter": "1",
            "text_sha256": digest(TEXT2),
            "kind": "synthetic",
            "spans": [],
        }
        rec = self.record(
            book_id="synthetic-demo",
            source_refs=[ref],
            metadata={"synthetic": True},
            target={"kind": "gloss", "answer": "Bounded data is processed together.", "citations": []},
        )
        rec = self.expect(
            rec,
            required_facts=[{"claim": "Batch processing handles bounded data.", "source_ids": ["s1"]}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])
        self.assertIn("synthetic_source", result["notes"])

        undeclared = copy.deepcopy(rec)
        undeclared.pop("metadata")
        self.sign(undeclared)
        bad = self.one(undeclared)
        self.assertEqual(bad["verdict"], "FAIL")
        self.assertIn("synthetic_undeclared", codes(bad))

    def test_intentional_absence_context_passes(self):
        rec = self.record(
            source_refs=[self.source()],
            provided_source_ids=[],
            absence_evidence={"reason": "deliberate no-context item; the model must refuse"},
            expected={
                "book_answerable": True,
                "evidence_sufficient": False,
                "allowed_behaviors": ["refuse"],
                "required_facts": [],
                "unsupported_claims": [],
            },
            target={"kind": "refusal", "answer": "Not in this book.", "refused": True},
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])
        self.assertIn("intentional_absence", result["notes"])

    def test_book_level_gold_that_expects_refusal_passes(self):
        """Book answers it, context withholds it, model must refuse: valid."""
        rec = self.record(
            provided_source_ids=[],
            expected={
                "book_answerable": True,
                "evidence_sufficient": False,
                "allowed_behaviors": ["refuse"],
                "required_facts": [
                    {"claim": "A watermark tracks how far a stream has progressed.", "source_ids": ["s1"]}
                ],
                "unsupported_claims": [],
            },
            target={"kind": "refusal", "answer": "Not in this book.", "refused": True},
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])
        self.assertIn("book_level_gold", result["notes"])

    def test_system_stage_with_insufficient_provided_context_is_a_diagnostic(self):
        """A pipeline item whose retrieval must still find gold is not invalid."""
        rec = self.expect(
            self.record(task_stage="system"),
            evidence_sufficient=False,
            allowed_behaviors=["answer"],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])
        self.assertIn("system_retrieval_diagnostic", result["notes"])

    def test_fact_witnesses_are_not_a_citation_whitelist(self):
        second = self.source(
            source_id="s2",
            chunk_id="ch03-001",
            chapter="3",
            text_sha256=digest(TEXT3),
            spans=[],
        )
        rec = self.record(source_refs=[self.source(), second], provided_source_ids=["s1", "s2"])
        rec = self.expect(
            rec,
            required_facts=[{"claim": "A watermark tracks progress.", "source_ids": ["s1"]}],
        )
        rec = self.target(rec, citations=["s2"])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_alternative_fact_sources_pass_when_one_witness_is_provided(self):
        second = self.source(
            source_id="s2",
            chunk_id="ch03-001",
            chapter="3",
            text_sha256=digest(TEXT3),
            spans=[],
        )
        rec = self.record(source_refs=[self.source(), second], provided_source_ids=["s1"])
        rec = self.expect(
            rec,
            required_facts=[
                {"claim": "A watermark tracks progress.", "source_ids": ["s1", "s2"]}
            ],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_joint_fact_sources_fail_when_one_witness_is_not_provided(self):
        second = self.source(
            source_id="s2",
            chunk_id="ch03-001",
            chapter="3",
            text_sha256=digest(TEXT3),
            spans=[],
        )
        rec = self.record(source_refs=[self.source(), second], provided_source_ids=["s1"])
        rec = self.expect(
            rec,
            required_facts=[
                {
                    "claim": "A watermark tracks progress jointly with batching.",
                    "source_ids": ["s1", "s2"],
                    "support_mode": "all",
                }
            ],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("gold_context_unprovided", codes(result))


class SourceTruthTest(Fixture):
    def test_wrong_quote_fails(self):
        ref = self.source(spans=[{"start": 0, "end": 11, "text": "A waterwall"}])
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("span_text_mismatch", codes(result))

    def test_quote_that_only_exists_at_other_offsets_fails(self):
        ref = self.source(spans=[{"start": 0, "end": 11, "text": "It moves with"}])
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("span_offsets_wrong", codes(result))

    def test_span_outside_the_source_fails(self):
        ref = self.source(spans=[{"start": 0, "end": len(TEXT1) + 50, "text": TEXT1}])
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("span_bounds", codes(result))

    def test_stale_index_hash_fails(self):
        ref = self.source(index_sha256="0" * 64)
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_index_stale", codes(result))

    def test_stale_chunk_text_hash_fails(self):
        ref = self.source(text_sha256=digest("some other text"))
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_text_hash_mismatch", codes(result))

    def test_wrong_chapter_fails(self):
        ref = self.source(chapter="2")
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_chapter_mismatch", codes(result))

    def test_missing_index_file_fails_closed(self):
        ref = self.source(index_path=str(self.tmp / "does-not-exist.json"))
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_index_missing", codes(result))

    def test_missing_source_reference_fails(self):
        result = self.one(self.record(provided_source_ids=["s1", "s9"]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("provided_source_unknown", codes(result))

    def test_duplicate_source_id_fails(self):
        second = self.source(chunk_id="ch02-001", chapter="2", text_sha256=digest(TEXT2), spans=[])
        result = self.one(self.record(source_refs=[self.source(), second]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_id_duplicate", codes(result))

    def test_ambiguous_chunk_id_fails(self):
        self._write_index(
            self.index_path,
            chunks=[
                {"chunk_id": "ch01-001", "chapter": "1", "text": TEXT1},
                {"chunk_id": "ch01-001", "chapter": "1", "text": TEXT2},
            ],
        )
        self.index_sha = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        result = self.one(self.record(source_refs=[self.source()]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_ambiguous", codes(result))

    def test_caption_without_figure_id_fails(self):
        ref = self.caption_source()
        ref.pop("figure_id")
        result = self.one(self.record(source_refs=[ref]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("caption_figure_missing", codes(result))

    def test_mixed_book_ids_fail(self):
        result = self.one(self.record(book_id="other-book"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("mixed_book_id", codes(result))

    def test_unknown_source_role_fails(self):
        result = self.one(self.record(source_refs=[self.source(role="gold-ish")]))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_role_invalid", codes(result))


class RefusalAndTargetTest(Fixture):
    def test_refusal_with_commentary_fails(self):
        rec = self.target(
            self.record(),
            kind="refusal",
            answer="Not in this book. The passage says nothing about it.",
            refused=True,
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("refusal_not_exact", codes(result))

    def test_exact_refusal_passes(self):
        rec = self.target(
            self.record(),
            kind="refusal",
            answer="Not in this book.",
            refused=True,
        )
        rec = self.expect(
            rec,
            book_answerable=False,
            evidence_sufficient=False,
            allowed_behaviors=["refuse"],
            required_facts=[],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_refusal_sentence_inside_a_real_answer_is_not_a_refusal(self):
        rec = self.target(
            self.record(),
            kind="answer",
            answer="It marks progress. Not in this book.",
            refused=False,
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_exact_refusal_sentence_declared_as_answer_or_gloss_fails(self):
        """The refusal sentence is a refusal only when the target says so."""
        for kind in ("answer", "gloss"):
            with self.subTest(kind=kind):
                rec = self.target(
                    self.record(),
                    kind=kind,
                    answer="Not in this book.",
                    refused=False,
                )
                result = self.one(rec)
                self.assertEqual(result["verdict"], "FAIL", result["findings"])
                self.assertIn("refusal_target_mislabelled", codes(result))

    def test_answer_target_without_citations_is_review(self):
        rec = self.target(self.record(), citations=[])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("uncited_answer_target", codes(result))

    def test_citation_not_in_provided_sources_fails(self):
        rec = self.target(self.record(), citations=["ch02-001"])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("citation_not_provided", codes(result))

    def test_refusal_on_answerable_evidence_is_review(self):
        rec = self.target(
            self.record(),
            kind="refusal",
            answer="Not in this book.",
            refused=True,
        )
        rec = self.expect(rec, allowed_behaviors=["refuse"], required_facts=[])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("refusal_on_answerable_book_question", codes(result))


class EvidenceAndReviewTest(Fixture):
    def test_keyword_only_truth_is_never_pass(self):
        """A bare term with no reviewer attestation stays REVIEW.

        No word-overlap check can turn a keyword into a fact, and the validator
        must not pretend it did.
        """
        rec = self.expect(
            self.record(),
            required_facts=[{"claim": "machine learning", "source_ids": ["s1"]}],
        )
        rec = self.review(rec, status="needs_review", notes="keyword found in the passage")
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertNotEqual(result["verdict"], "PASS")

    def test_required_fact_without_acceptance_blocks_pass(self):
        rec = self.review(self.record(), status="needs_review")
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("facts_unreviewed", codes(result))

    def test_self_review_fails(self):
        rec = self.review(self.record(), reviewer="author-a")
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("self_review", codes(result))

    def test_rejected_review_fails(self):
        result = self.one(self.review(self.record(), status="rejected"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("review_rejected", codes(result))

    def test_fact_citing_an_undeclared_source_fails(self):
        rec = self.expect(
            self.record(),
            required_facts=[{"claim": "A watermark tracks progress.", "source_ids": ["s9"]}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("fact_source_missing", codes(result))

    def test_unknown_fact_support_mode_fails(self):
        rec = self.expect(
            self.record(),
            required_facts=[
                {
                    "claim": "A watermark tracks progress.",
                    "source_ids": ["s1"],
                    "support_mode": "either",
                }
            ],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("support_mode_invalid", codes(result))

    def test_gold_context_withheld_from_a_model_answer_fails(self):
        rec = self.expect(
            self.record(),
            required_facts=[
                {"claim": "Batch processing handles bounded data.", "source_ids": ["s2"]}
            ],
        )
        second = self.source(
            source_id="s2",
            chunk_id="ch02-001",
            chapter="2",
            text_sha256=digest(TEXT2),
            spans=[],
        )
        rec["source_refs"] = [self.source(), second]
        self.sign(rec)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("gold_context_unprovided", codes(result))

    def test_insufficient_evidence_with_an_answer_target_fails(self):
        rec = self.expect(
            self.record(),
            evidence_sufficient=False,
            allowed_behaviors=["answer"],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("answer_with_insufficient_evidence", codes(result))

    def test_refusal_with_no_context_but_sufficient_evidence_is_review(self):
        rec = self.record(
            provided_source_ids=[],
            expected={
                "book_answerable": False,
                "evidence_sufficient": True,
                "allowed_behaviors": ["refuse"],
                "required_facts": [],
                "unsupported_claims": [],
            },
            target={"kind": "refusal", "answer": "Not in this book.", "refused": True},
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("absence_unexplained", codes(result))

    def test_absence_evidence_without_a_reason_fails(self):
        rec = self.record(
            provided_source_ids=[],
            absence_evidence={"why": "no context on purpose"},
            expected={
                "book_answerable": False,
                "evidence_sufficient": False,
                "allowed_behaviors": ["refuse"],
                "required_facts": [],
                "unsupported_claims": [],
            },
            target={"kind": "refusal", "answer": "Not in this book.", "refused": True},
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("schema", codes(result))

    def test_unknown_answerability_is_review_on_an_eval_split(self):
        rec = self.expect(self.record(), book_answerable=None)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("book_answerability_unknown", codes(result))

    def test_unknown_answerability_is_allowed_on_a_train_split(self):
        rec = self.expect(self.record(split="train"), book_answerable=None)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])


class LeakageTest(Fixture):
    def test_family_across_splits_fails(self):
        train = self.record(id="t-1", split="train", source_refs=[self.source(chunk_id="ch03-001", chapter="3", text_sha256=digest(TEXT3), spans=[])])
        dev = self.record(id="d-1", split="dev", family_id="family-a")
        report = self.check(train, dev)
        self.assertEqual(report["verdict"], "FAIL")
        dev_result = next(r for r in report["records"] if r["id"] == "d-1")
        self.assertIn("family_split_leak", codes(dev_result))

    def test_same_support_chunk_across_splits_fails(self):
        train = self.record(id="t-1", split="train", family_id="family-t")
        dev = self.record(id="d-1", split="dev", family_id="family-d")
        report = self.check(train, dev)
        self.assertEqual(report["verdict"], "FAIL")
        dev_result = next(r for r in report["records"] if r["id"] == "d-1")
        self.assertIn("source_component_split_leak", codes(dev_result))

    def test_same_text_under_a_rebuilt_index_fails(self):
        other_index = self.tmp / "index.rebuilt.json"
        self._write_index(other_index)
        other_sha = hashlib.sha256(other_index.read_bytes()).hexdigest()
        train = self.record(
            id="t-1",
            split="train",
            family_id="family-t",
            question="Why does a watermark matter?",
        )
        dev_ref = self.source(
            index_path=str(other_index),
            index_sha256=other_sha,
            spans=[{"start": 0, "end": 11, "text": "A watermark"}],
        )
        dev = self.record(id="d-1", split="dev", family_id="family-d", source_refs=[dev_ref])
        report = self.check(train, dev)
        self.assertEqual(report["verdict"], "FAIL")
        dev_result = next(r for r in report["records"] if r["id"] == "d-1")
        self.assertIn("source_text_split_leak", codes(dev_result))

    def test_context_only_distractor_across_splits_is_counted_not_failed(self):
        distractor = self.source(
            source_id="s2",
            chunk_id="ch03-001",
            chapter="3",
            text_sha256=digest(TEXT3),
            spans=[],
            role="distractor",
        )
        train = self.record(
            id="t-1",
            split="train",
            family_id="family-t",
            question="Why is batching useful?",
            source_refs=[distractor],
            provided_source_ids=["s1", "s2"],
            target={"kind": "gloss", "answer": "Batching groups bounded data.", "citations": []},
            expected={
                "book_answerable": True,
                "evidence_sufficient": True,
                "allowed_behaviors": ["answer"],
                "required_facts": [{"claim": "Batch processing handles bounded data.", "source_ids": ["s1"]}],
                "unsupported_claims": [],
            },
        )
        # The train row's own support is ch02-001 (the corpus witness); make the
        # support explicit so the only ch03 reuse is the distractor.
        train["source_refs"] = [
            self.source(source_id="s1", chunk_id="ch02-001", chapter="2", text_sha256=digest(TEXT2), spans=[]),
            distractor,
        ]
        self.sign(train)
        dev = self.record(
            id="d-1",
            split="dev",
            family_id="family-d",
            source_refs=[self.source(), copy.deepcopy(distractor)],
            provided_source_ids=["s1", "s2"],
        )
        report = self.check(train, dev)
        self.assertEqual(report["integrity"]["verdict"], "PASS", report["records"])
        self.assertEqual(report["lineage"]["verdict"], "PASS", report["records"])
        self.assertEqual(report["lineage"]["context_only_overlaps"], 1)
        self.assertNotIn("source_component_split_leak", codes(report["records"][1]))

    def test_refusal_nearby_source_across_splits_is_not_a_leak(self):
        nearby = self.source(
            source_id="s2",
            chunk_id="ch03-001",
            chapter="3",
            text_sha256=digest(TEXT3),
            spans=[],
            role="refusal_nearby",
        )
        train = self.record(
            id="t-1",
            split="train",
            family_id="family-t",
            question="Why is batching useful?",
            source_refs=[
                self.source(source_id="s1", chunk_id="ch02-001", chapter="2", text_sha256=digest(TEXT2), spans=[]),
                copy.deepcopy(nearby),
            ],
            provided_source_ids=["s1", "s2"],
            target={"kind": "gloss", "answer": "Batching groups bounded data.", "citations": []},
            expected={
                "book_answerable": True,
                "evidence_sufficient": True,
                "allowed_behaviors": ["answer"],
                "required_facts": [{"claim": "Batch processing handles bounded data.", "source_ids": ["s1"]}],
                "unsupported_claims": [],
            },
        )
        dev = self.record(
            id="d-1",
            split="dev",
            family_id="family-d",
            source_refs=[self.source(), copy.deepcopy(nearby)],
            provided_source_ids=["s1", "s2"],
        )
        report = self.check(train, dev)
        self.assertEqual(report["lineage"]["verdict"], "PASS", report["records"])
        self.assertNotIn(
            "source_component_split_leak",
            {c for r in report["records"] for c in codes(r)},
        )

    def test_exact_duplicate_same_split_is_review_not_fail(self):
        first = self.record(id="a-1", family_id="family-a")
        second = self.record(
            id="a-2", family_id="family-b", question="What IS a watermark"
        )
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(report["counts"]["fail"], 0)
        self.assertIn("duplicate_full_input", codes(report["records"][1]))
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 1)

    def test_declared_paraphrase_across_splits_fails(self):
        train = self.record(
            id="t-1",
            split="train",
            family_id="family-t",
            source_refs=[self.source(chunk_id="ch03-001", chapter="3", text_sha256=digest(TEXT3), spans=[])],
        )
        dev = self.record(id="d-1", split="dev", family_id="family-d", metadata={"paraphrase_of": "t-1"})
        report = self.check(train, dev)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("paraphrase_split_leak", codes(report["records"][1]))

    def test_train_record_without_a_corpus_labels_lineage_unknown(self):
        report = self.check(self.record(split="train"), train_corpus=None)
        self.assertEqual(report["integrity"]["verdict"], "PASS")
        self.assertEqual(report["lineage"]["status"], "unknown")
        self.assertEqual(report["lineage"]["provenance"], "unknown")
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertIn("train_corpus_absent", {f["code"] for f in report["findings"]})

    def test_eval_only_dataset_without_a_corpus_also_labels_lineage_unknown(self):
        report = self.check(self.record(split="dev"), train_corpus=None)
        self.assertEqual(report["integrity"]["verdict"], "PASS")
        self.assertEqual(report["lineage"]["status"], "unknown")
        self.assertEqual(report["verdict"], "REVIEW")

    def test_corpus_path_that_does_not_exist_fails_closed(self):
        report = self.check(
            self.record(split="dev"),
            train_corpus=str(self.tmp / "missing-corpus.jsonl"),
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertIn("train_corpus_missing", {f["code"] for f in report["findings"]})

    def test_legacy_corpus_rows_are_unknown_not_clean(self):
        corpus = self.tmp / "legacy.jsonl"
        corpus.write_text(
            json.dumps({"messages": [{"role": "user", "content": "Question: x"}]}) + "\n",
            encoding="utf-8",
        )
        report = self.check(self.record(split="dev"), train_corpus=str(corpus))
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(report["lineage"]["status"], "unknown")
        self.assertEqual(report["lineage"]["provenance"], "unknown")
        self.assertGreater(report["lineage"]["train_rows_without_provenance"], 0)
        self.assertIn(
            "train_provenance_missing", {f["code"] for f in report["findings"]}
        )

    def test_canonical_corpus_family_leak_fails(self):
        corpus = self.dataset_file("corpus-leak.jsonl", [self.record(id="c-1", split="train")])
        report = self.check(
            self.record(id="d-1", split="dev", family_id="family-a"),
            train_corpus=str(corpus),
        )
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["lineage"]["status"], "checked")
        self.assertIn("family_split_leak", codes(report["records"][0]))

    def test_corpus_with_no_train_records_is_review(self):
        corpus = self.tmp / "empty.jsonl"
        corpus.write_text("", encoding="utf-8")
        report = self.check(self.record(split="dev"), train_corpus=str(corpus))
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertIn("train_corpus_empty", {f["code"] for f in report["findings"]})

    def test_duplicate_ids_fail(self):
        report = self.check(self.record(id="same"), self.record(id="same", family_id="family-b"))
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(
            any("duplicate_id" in codes(r) for r in report["records"]), report["records"]
        )

    def corpus_leak(self, corpus_row, dev_ref):
        """Run one dev item that grades ``dev_ref``'s chunk against a corpus row."""
        dev = self.record(
            id="dev-1",
            split="dev",
            family_id="family-dev",
            question="How does schema evolution change a table?",
            source_refs=[dev_ref],
            provided_source_ids=["s1"],
        )
        dev_path = self.dataset_file("dev-split.jsonl", [dev])
        corpus_path = self.dataset_file("corpus-split.jsonl", [corpus_row])
        report = DI.check_datasets([str(dev_path)], train_corpus=str(corpus_path))
        return report, report["records"][0]

    def test_corpus_distractor_fact_witness_is_support_exposure(self):
        """A corpus passage its fact grades is support even if labelled a distractor.

        The same row submitted as a dataset ``split: "train"`` record already
        fails the dev item; the corpus path must classify exposure the same way.
        """
        row = self.record(
            id="corpus-1",
            split="train",
            family_id="family-corpus",
            question="How does schema evolution work?",
            source_refs=[
                self.source(
                    chunk_id="ch03-001",
                    chapter="3",
                    text_sha256=digest(TEXT3),
                    spans=[],
                    role="distractor",
                )
            ],
            provided_source_ids=["s1"],
            target={"kind": "gloss", "answer": "The table changes in place.", "citations": []},
        )
        row = self.expect(
            row,
            required_facts=[
                {"claim": "Schema evolution changes a table without a rewrite.", "source_ids": ["s1"]}
            ],
        )
        dev_ref = self.source(
            chunk_id="ch03-001", chapter="3", text_sha256=digest(TEXT3), spans=[]
        )
        report, dev = self.corpus_leak(row, dev_ref)
        self.assertEqual(dev["verdict"], "FAIL", dev["findings"])
        self.assertIn("source_component_split_leak", codes(dev))
        self.assertIn("source_text_split_leak", codes(dev))
        self.assertEqual(report["lineage"]["context_only_overlaps"], 0)

    def test_corpus_extra_support_ref_is_support_exposure(self):
        """role="support" is support even when no fact names it."""
        row = self.record(
            id="corpus-1",
            split="train",
            family_id="family-corpus",
            question="How does schema evolution work?",
            source_refs=[
                self.source(source_id="s1", chunk_id="ch01-001", chapter="1", spans=[]),
                self.source(
                    source_id="s2",
                    chunk_id="ch03-001",
                    chapter="3",
                    text_sha256=digest(TEXT3),
                    spans=[],
                    role="support",
                ),
            ],
            provided_source_ids=["s1", "s2"],
            target={"kind": "gloss", "answer": "Watermarks and tables.", "citations": ["s1"]},
        )
        dev_ref = self.source(
            chunk_id="ch03-001", chapter="3", text_sha256=digest(TEXT3), spans=[]
        )
        report, dev = self.corpus_leak(row, dev_ref)
        self.assertEqual(dev["verdict"], "FAIL", dev["findings"])
        self.assertIn("source_component_split_leak", codes(dev))
        self.assertIn("source_text_split_leak", codes(dev))
        self.assertEqual(report["lineage"]["context_only_overlaps"], 0)

    def test_corpus_unused_distractor_stays_context_only(self):
        """Control: a corpus passage nothing uses is context, counted not failed."""
        row = self.record(
            id="corpus-1",
            split="train",
            family_id="family-corpus",
            question="How does schema evolution work?",
            source_refs=[
                self.source(source_id="s1", chunk_id="ch01-001", chapter="1", spans=[]),
                self.source(
                    source_id="s2",
                    chunk_id="ch03-001",
                    chapter="3",
                    text_sha256=digest(TEXT3),
                    spans=[],
                    role="distractor",
                ),
            ],
            provided_source_ids=["s1", "s2"],
            target={"kind": "gloss", "answer": "It marks progress.", "citations": ["s1"]},
        )
        dev_ref = self.source(
            chunk_id="ch03-001", chapter="3", text_sha256=digest(TEXT3), spans=[]
        )
        report, dev = self.corpus_leak(row, dev_ref)
        self.assertEqual(dev["verdict"], "PASS", dev["findings"])
        self.assertNotIn("source_component_split_leak", codes(dev))
        self.assertEqual(report["lineage"]["context_only_overlaps"], 1)


class FailClosedTest(Fixture):
    def test_schema_errors_are_fail_records_not_dropped_rows(self):
        rec = self.record()
        rec.pop("id")
        rec.pop("split")
        report = self.check(rec)
        self.assertEqual(report["counts"]["records"], 1)
        self.assertEqual(report["counts"]["fail"], 1)
        self.assertIn("schema", codes(report["records"][0]))

    def test_unreadable_line_is_counted_and_fails(self):
        path = self.tmp / "broken.jsonl"
        path.write_text(
            json.dumps(self.record()) + "\n" + "{not json}\n", encoding="utf-8"
        )
        report = DI.check_datasets([str(path)], train_corpus=str(self.corpus))
        self.assertEqual(report["counts"]["records"], 2)
        self.assertEqual(report["counts"]["unreadable"], 1)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertTrue(report["records"][1]["unreadable"])

    def test_counts_account_for_every_record(self):
        records = [
            self.record(id="a", family_id="f1"),
            self.record(id="b", family_id="f2", question="What is batch processing?"),
            self.target(self.record(id="c", family_id="f3", question="What is a stream?"), citations=[]),
        ]
        report = self.check(*records)
        counts = report["counts"]
        self.assertEqual(counts["records"], 3)
        self.assertEqual(counts["records"], counts["pass"] + counts["fail"] + counts["review"])

    def test_a_fabricated_dataset_fails_on_several_independent_rules(self):
        """Negative control: a row that looks like data and is not."""
        bogus_ref = self.source(
            chunk_id="ch99-999",
            chapter="99",
            text_sha256="0" * 64,
            index_sha256="f" * 64,
            spans=[{"start": 0, "end": 12, "text": "A watermark is"}],
        )
        wrong_chapter = self.source(source_id="s2", chapter="2", spans=[])
        rec = self.target(
            self.record(
                source_refs=[bogus_ref, wrong_chapter],
                provided_source_ids=["s1", "s2"],
                book_id="other-book",
                review={
                    "status": "accepted",
                    "author": "same",
                    "reviewer": "same",
                    "notes": "",
                    "provenance": "agent",
                },
            ),
            kind="refusal",
            answer="Not in this book. Probably.",
            refused=True,
        )
        report = self.check(rec)
        self.assertEqual(report["verdict"], "FAIL")
        fired = codes(report["records"][0])
        for expected in (
            "source_index_stale",
            "source_missing",
            "source_chapter_mismatch",
            "refusal_not_exact",
            "self_review",
        ):
            self.assertIn(expected, fired)


class ReviewBindingTest(Fixture):
    """An accepted review must cover the bytes that were reviewed.

    A reviewer's name is not an attestation about content: without a digest,
    any author can rewrite the claim, question, target, or sources after
    approval and keep the tick.
    """

    def assert_not_pass(self, result, code):
        self.assertNotEqual(result["verdict"], "PASS", result)
        self.assertIn(code, codes(result))

    def test_accepted_review_binds_the_record(self):
        base = self.sign(self.record())
        self.assertEqual(self.one(base)["verdict"], "PASS")

        def claim(rec):
            rec["expected"]["required_facts"][0]["claim"] = "A watermark measures disk latency."

        def question(rec):
            rec["question"] = "How fast is the disk?"

        def target(rec):
            rec["target"]["answer"] = "It measures disk latency."

        def history(rec):
            rec["history"] = [{"question": "Earlier turn?", "answer": "Earlier answer."}]

        def sources(rec):
            start = TEXT1.index("It moves with the data.")
            rec["source_refs"][0]["spans"] = [
                {"start": start, "end": start + 22, "text": "It moves with the data."}
            ]

        def split(rec):
            rec["split"] = "test"

        def family(rec):
            rec["family_id"] = "family-renamed"

        def origin(rec):
            rec["origin"]["record"] = 99

        for name, mutate in (
            ("claim", claim),
            ("question", question),
            ("target", target),
            ("history", history),
            ("source_refs", sources),
            ("split", split),
            ("family_id", family),
            ("origin", origin),
        ):
            with self.subTest(mutated=name):
                changed = copy.deepcopy(base)
                mutate(changed)
                self.assert_not_pass(self.one(changed), "review_digest_stale")

    def test_missing_review_digest_fails(self):
        rec = self.sign(self.record())
        del rec["review"]["content_sha256"]
        self.assert_not_pass(self.one(rec), "review_digest_missing")

    def test_missing_criteria_version_fails(self):
        rec = self.sign(self.record())
        del rec["review"]["criteria_version"]
        self.assert_not_pass(self.one(rec), "review_criteria_missing")

    def test_needs_review_needs_no_binding(self):
        rec = self.sign(self.record())
        del rec["review"]["content_sha256"]
        rec["review"]["status"] = "needs_review"
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertNotIn("review_digest_missing", codes(result))

    def test_review_digest_matches_the_documented_algorithm(self):
        rec = self.sign(self.record())
        payload = {key: value for key, value in rec.items() if key != "review"}
        expected = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(DI.review_digest(rec), expected)
        changed = copy.deepcopy(rec)
        changed["review"] = {"status": "accepted", "notes": "another review block"}
        self.assertEqual(DI.review_digest(changed), expected, "review must be excluded")

    def test_non_json_metadata_fails_instead_of_crashing(self):
        rec = self.record()
        rec["metadata"] = {"tags": {"a", "b"}}  # a set: not canonical JSON
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("schema", codes(result))

    def test_agent_and_owner_attestations_are_reported_separately(self):
        agent = self.sign(self.record(id="a-1", family_id="family-a"))
        owner = self.sign(
            self.record(id="b-1", family_id="family-b", question="What is batching?")
        )
        owner["review"] = {
            "status": "accepted",
            "author": "author-a",
            "reviewer": "owner-c",
            "notes": "owner checked it",
            "provenance": "owner",
            "criteria_version": "source-grounding-v1",
        }
        self.sign(owner)
        report = self.check(agent, owner)
        self.assertEqual(report["review"]["agent"], 1)
        self.assertEqual(report["review"]["owner"], 1)
        self.assertEqual(report["review"]["criteria_versions"], ["source-grounding-v1"])


class OriginAndReleaseTest(Fixture):
    def test_origin_pointing_at_the_output_dataset_fails(self):
        path = self.tmp / "self-origin.jsonl"
        rec = self.record()
        rec["origin"]["path"] = str(path)
        self.sign(rec)
        path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        report = DI.check_datasets([str(path)], train_corpus=str(self.corpus))
        self.assertEqual(report["records"][0]["verdict"], "FAIL")
        self.assertIn("origin_self_reference", codes(report["records"][0]))

    def test_origin_verification_is_labelled_when_skipped(self):
        path = self.dataset_file("origin-label.jsonl", [self.record()])
        unchecked = DI.check_datasets([str(path)], train_corpus=str(self.corpus))
        self.assertEqual(unchecked["origin_verification"], "not_checked")
        checked = DI.check_datasets(
            [str(path)], train_corpus=str(self.corpus), verify_origins=True
        )
        self.assertEqual(checked["origin_verification"], "checked")

    def test_release_refuses_to_run_without_origin_verification(self):
        path = self.dataset_file("release.jsonl", [self.record()])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = DI.main(
                ["--dataset", str(path), "--train-corpus", str(self.corpus), "--release"]
            )
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["scope"], "release")
        self.assertIn(
            "release_requires_origin_verification",
            {finding["code"] for finding in report["findings"]},
        )

    def test_release_with_origin_verification_passes(self):
        path = self.dataset_file("release-ok.jsonl", [self.record()])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = DI.main(
                [
                    "--dataset",
                    str(path),
                    "--train-corpus",
                    str(self.corpus),
                    "--release",
                    "--verify-origins",
                ]
            )
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 0, report)
        self.assertEqual(report["scope"], "release")
        self.assertEqual(report["origin_verification"], "checked")


class DuplicateScopeTest(Fixture):
    """A repeated question is not a repeated input.

    "Why does it matter?" under different history, book, and sources is two
    independent items. Only the same full model input is a duplicate, and
    declared variants (same family or paraphrase_of) are not accidents.
    """

    def second_book_record(self, **over):
        other = self.tmp / "index.two.json"
        self._write_index(
            other,
            book_id="demo-two",
            chunks=[{"chunk_id": "ch01-001", "chapter": "1", "text": TEXT4}],
            figures=[],
        )
        sha = hashlib.sha256(other.read_bytes()).hexdigest()
        ref = {
            "source_id": "s1",
            "book_id": "demo-two",
            "index_path": str(other),
            "index_sha256": sha,
            "chunk_id": "ch01-001",
            "chapter": "1",
            "text_sha256": digest(TEXT4),
            "spans": [],
        }
        rec = self.record(
            book_id="demo-two",
            source_refs=[ref],
            provided_source_ids=["s1"],
            **over,
        )
        rec["expected"]["required_facts"] = [
            {"claim": "A stream arrives over time.", "source_ids": ["s1"]}
        ]
        rec["target"]["citations"] = ["s1"]
        return self.sign(rec)

    def test_same_question_with_different_context_is_not_a_duplicate(self):
        first = self.record(id="ctx-1", family_id="family-a", question="Why does it matter?")
        second = self.second_book_record(
            id="ctx-2",
            family_id="family-b",
            question="Why does it matter?",
            history=[{"question": "Earlier?", "answer": "Earlier answer."}],
        )
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "PASS", report["records"])
        self.assertEqual(report["duplicates"]["question_repeats"], 1)
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 0)
        self.assertEqual(report["duplicates"]["independent_records"], 2)
        for result in report["records"]:
            self.assertNotIn("duplicate_question", codes(result))
            self.assertNotIn("duplicate_question_across_splits", codes(result))

    def test_identical_input_with_renamed_source_id_is_still_a_duplicate(self):
        first = self.record(id="dup-1", family_id="family-a")
        second = self.record(id="dup-2", family_id="family-b")
        second["source_refs"] = [self.source(source_id="support-x")]
        second["provided_source_ids"] = ["support-x"]
        second["expected"]["required_facts"] = [
            {"claim": "A watermark tracks progress.", "source_ids": ["support-x"]}
        ]
        second["target"]["citations"] = ["support-x"]
        self.sign(second)
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "REVIEW", report["records"])
        self.assertIn("duplicate_full_input", codes(report["records"][1]))
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 1)
        self.assertEqual(report["duplicates"]["independent_records"], 1)

    def test_identical_input_across_splits_is_review_without_a_support_leak(self):
        def refusal(cid, split, family):
            return self.record(
                id=cid,
                split=split,
                family_id=family,
                source_refs=[
                    self.source(
                        source_id="s1",
                        chunk_id="ch03-001",
                        chapter="3",
                        text_sha256=digest(TEXT3),
                        spans=[],
                        role="distractor",
                    )
                ],
                provided_source_ids=["s1"],
                expected={
                    "book_answerable": False,
                    "evidence_sufficient": False,
                    "allowed_behaviors": ["refuse"],
                    "required_facts": [],
                    "unsupported_claims": [],
                },
                target={"kind": "refusal", "answer": "Not in this book.", "refused": True},
            )

        train = refusal("r-t", "train", "family-t")
        dev = refusal("r-d", "dev", "family-d")
        report = self.check(train, dev)
        self.assertEqual(report["verdict"], "REVIEW", report["records"])
        self.assertIn("duplicate_full_input_across_splits", codes(report["records"][1]))
        self.assertEqual(report["lineage"]["context_only_overlaps"], 1)
        self.assertEqual(report["duplicates"]["independent_records"], 1)

    def test_linked_minimal_pair_is_a_variant_not_a_duplicate(self):
        first = self.record(id="mp-1", family_id="family-watermark")
        second = self.record(
            id="mp-2",
            family_id="family-watermark",
            question="what is a watermark",
        )
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "PASS", report["records"])
        self.assertEqual(report["duplicates"]["question_repeats"], 1)
        self.assertEqual(report["duplicates"]["variants"], 1)
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 0)
        self.assertEqual(report["duplicates"]["independent_records"], 1)

    def test_paraphrase_linked_variant_is_not_a_duplicate(self):
        first = self.record(id="pv-1", family_id="family-a")
        second = self.record(
            id="pv-2",
            family_id="family-b",
            question="what is a watermark",
            metadata={"paraphrase_of": "pv-1"},
        )
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "PASS", report["records"])
        self.assertEqual(report["duplicates"]["variants"], 1)
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 0)

    def test_exact_train_duplicate_is_review_and_not_removed(self):
        first = self.record(id="tr-1", split="train", family_id="family-a")
        second = self.record(id="tr-2", split="train", family_id="family-b")
        report = self.check(first, second)
        self.assertEqual(report["verdict"], "REVIEW", report["records"])
        self.assertEqual(report["counts"]["records"], 2)
        self.assertIn("duplicate_full_input", codes(report["records"][1]))
        self.assertEqual(report["duplicates"]["full_input_duplicates"], 1)

    def test_invalid_rows_do_not_enter_the_independent_count(self):
        report = self.check({"schema_version": 1})
        self.assertEqual(report["counts"]["records"], 1)
        self.assertEqual(report["duplicates"]["independent_records"], 0)

    def test_source_hash_violation_fails_under_an_accepted_bound_review(self):
        rec = self.record()
        self.assertEqual(rec["review"]["status"], "accepted")
        rec["source_refs"][0]["text_sha256"] = digest("not the chunk")
        self.sign(rec)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("source_text_hash_mismatch", codes(result))


class TargetQuoteTest(Fixture):
    """A literal book quote in the target is a claim, and it is checked.

    A valid span, a matching text hash, and a freshly bound review say nothing
    about a sentence the author typed under the tag.
    """

    def wrapped_ref(self):
        return self.source(
            source_id="s1",
            chunk_id="ch02-002",
            chapter="2",
            text_sha256=digest(WRAPPED),
            spans=[],
        )

    def same_chapter_sibling(self, chunk_id="ch01-002", text=TEXT4):
        return self.source(
            source_id="s2",
            chunk_id=chunk_id,
            chapter="1",
            text_sha256=digest(text),
            spans=[],
        )

    def duplicate_text_sibling(self):
        return self.source(
            source_id="s2",
            chunk_id="ch01-003",
            chapter="1",
            text_sha256=digest(TEXT1),
            spans=[],
        )

    def test_invented_marked_quote_fails(self):
        rec = self.target(
            self.record(),
            answer='[Ch. 1] "A watermark is a magical unicorn."\nIt marks progress.',
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_forged_citation_quote_with_a_valid_body_fails(self):
        rec = self.target(
            self.record(),
            answer="It marks progress.",
            citations=[{"source_id": "s1", "quote": "An entirely invented sentence."}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_verbatim_marked_quote_passes(self):
        rec = self.target(
            self.record(),
            answer=f'[Ch. 1] "{QUOTE_SENTENCE}"\nIt marks progress.',
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_wrong_tag_cannot_widen_to_another_source(self):
        second = self.source(
            source_id="s2",
            chunk_id="ch02-001",
            chapter="2",
            text_sha256=digest(TEXT2),
            spans=[],
        )
        rec = self.record(source_refs=[self.source(), second], provided_source_ids=["s1", "s2"])
        rec = self.target(rec, answer=f'[Ch. 2] "{QUOTE_SENTENCE}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_tag_naming_an_unprovided_chapter_fails(self):
        rec = self.target(self.record(), answer=f'[Ch. 9] "{QUOTE_SENTENCE}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_chapter_unmatched", codes(result))

    def test_chapter_tag_matches_one_of_two_same_chapter_sources(self):
        rec = self.record(
            source_refs=[self.source(), self.same_chapter_sibling()],
            provided_source_ids=["s1", "s2"],
        )
        rec = self.target(rec, answer=f'[Ch. 1] "{QUOTE_SENTENCE}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_ambiguous_same_chapter_tag_is_review(self):
        rec = self.record(
            source_refs=[self.source(), self.duplicate_text_sibling()],
            provided_source_ids=["s1", "s2"],
        )
        rec = self.target(rec, answer=f'[Ch. 1] "{QUOTE_SENTENCE}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW", result["findings"])
        self.assertIn("target_quote_ambiguous", codes(result))

    def test_explicit_chunk_id_matches_only_that_source(self):
        rec = self.record(
            source_refs=[self.source(), self.duplicate_text_sibling()],
            provided_source_ids=["s1", "s2"],
        )
        rec = self.target(
            rec,
            answer="It marks progress.",
            citations=[{"chunk_id": "ch01-001", "quote": QUOTE_SENTENCE}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_explicit_chunk_id_not_provided_fails(self):
        rec = self.target(
            self.record(),
            citations=[{"chunk_id": "ch02-001", "quote": QUOTE_SENTENCE}],
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_source_unmatched", codes(result))

    def test_explicit_unknown_chunk_id_in_tag_fails(self):
        rec = self.target(
            self.record(), answer=f'[Ch. 1 ch99-999] "{QUOTE_SENTENCE}"'
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_source_unmatched", codes(result))

    def test_empty_marked_quote_is_review(self):
        rec = self.target(self.record(), answer='[Ch. 1] ""')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW", result["findings"])
        self.assertIn("target_quote_unparsed", codes(result))

    def test_short_invented_quote_is_not_skipped(self):
        rec = self.target(self.record(), answer='[Ch. 1] "fake"\nIt marks progress.')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_unclosed_marked_quote_is_review(self):
        rec = self.target(
            self.record(),
            answer='[Ch. 1] "A watermark is a threshold\nIt marks progress.',
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW", result["findings"])
        self.assertIn("target_quote_unparsed", codes(result))

    def test_wrapped_quote_matching_the_source_passes(self):
        rec = self.record(source_refs=[self.wrapped_ref()])
        rec = self.target(
            rec, answer=f'[Ch. 2] "{WRAPPED}"\nIt keeps one copy.'
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_wrapped_quote_with_a_mismatched_second_line_fails(self):
        broken = WRAPPED.replace("single copy", "one copy")
        rec = self.record(source_refs=[self.wrapped_ref()])
        rec = self.target(rec, answer=f'[Ch. 2] "{broken}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_unfinished_quote_is_review_and_does_not_consume_the_next(self):
        answer = (
            '[Ch. 2] "Consistency matters for every reader.\n'
            '[Ch. 2] "It refers to a single copy of the data."\n'
            "It keeps one copy."
        )
        rec = self.record(source_refs=[self.wrapped_ref()])
        rec = self.target(rec, answer=answer)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "REVIEW", result["findings"])
        self.assertIn("target_quote_unparsed", codes(result))
        self.assertNotIn("target_quote_not_in_source", codes(result))

    def named_index(self, name, chunks):
        path = self.tmp / name
        self._write_index(path, chunks=chunks, figures=[])
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_equivalent_chapter_labels_resolve(self):
        """A [Ch. …] tag resolves an equivalent chapter label, not only a bare number.

        Index labels from other books: ``chapter-4``, a titled chapter, an
        appendix, and a named front-matter section.
        """
        cases = (
            ("chapter-4", "[Ch. 4]"),
            ("chapter-4", "[Ch. chapter-4]"),
            ("Appendix A: Tables", "[Ch. appendix-a]"),
            ("preface", "[Ch. preface]"),
        )
        for position, (label, tag) in enumerate(cases):
            with self.subTest(chapter=label, tag=tag):
                path, sha = self.named_index(
                    f"index.named-{position}.json",
                    [{"chunk_id": "ch04-001", "chapter": label, "text": TEXT3}],
                )
                ref = self.source(
                    chunk_id="ch04-001",
                    chapter=label,
                    index_path=str(path),
                    index_sha256=sha,
                    text_sha256=digest(TEXT3),
                    spans=[],
                )
                rec = self.record(source_refs=[ref], provided_source_ids=["s1"])
                rec = self.target(rec, answer=f'{tag} "{TEXT3}"')
                result = self.one(rec)
                self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_equivalent_chapter_key_cannot_cross_to_another_chapter(self):
        """The label key resolves one chapter, never the whole provided set."""
        path, sha = self.named_index(
            "index.named-two.json",
            [
                {"chunk_id": "ch04-001", "chapter": "chapter-4", "text": TEXT3},
                {"chunk_id": "ch05-001", "chapter": "chapter-5", "text": TEXT2},
            ],
        )
        first = self.source(
            chunk_id="ch04-001",
            chapter="chapter-4",
            index_path=str(path),
            index_sha256=sha,
            text_sha256=digest(TEXT3),
            spans=[],
        )
        second = self.source(
            source_id="s2",
            chunk_id="ch05-001",
            chapter="chapter-5",
            index_path=str(path),
            index_sha256=sha,
            text_sha256=digest(TEXT2),
            spans=[],
        )
        rec = self.record(source_refs=[first, second], provided_source_ids=["s1", "s2"])
        rec = self.target(rec, answer=f'[Ch. 4] "{TEXT2}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def chapter_record(self, path, sha, chunks, tag, quote, citations):
        refs = [
            self.source(
                source_id=f"s{position}",
                chunk_id=chunk["chunk_id"],
                chapter=chunk["chapter"],
                index_path=str(path),
                index_sha256=sha,
                text_sha256=digest(chunk["text"]),
                spans=[],
            )
            for position, chunk in enumerate(chunks, 1)
        ]
        rec = self.record(
            source_refs=refs,
            provided_source_ids=[ref["source_id"] for ref in refs],
        )
        return self.target(rec, answer=f'{tag} "{quote}"', citations=citations)

    def test_chapter_range_and_slash_tags_resolve_each_member(self):
        """``[Ch. 4-5]`` and ``[Ch. 4/5]`` name both chapters, not one label."""
        chunks = [
            {"chunk_id": "ch04-001", "chapter": "4", "text": TEXT3},
            {"chunk_id": "ch05-001", "chapter": "5", "text": TEXT1},
        ]
        path, sha = self.named_index("index.range.json", chunks)
        for tag in ("[Ch. 4-5]", "[Ch. 4/5]"):
            for position, chunk in enumerate(chunks, 1):
                with self.subTest(tag=tag, chunk=chunk["chunk_id"]):
                    rec = self.chapter_record(
                        path, sha, chunks, tag, chunk["text"], [f"s{position}"]
                    )
                    result = self.one(rec)
                    self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_named_chapter_labels_fold_case_and_separators(self):
        """A named chapter label compares by words, not by hyphen or case."""
        cases = (
            ("Front Matter", "[Ch. front-matter]"),
            ("Front Matter", "[Ch. FrontMatter]"),
            ("front-matter", "[Ch. Front Matter]"),
        )
        for position, (label, tag) in enumerate(cases):
            with self.subTest(chapter=label, tag=tag):
                chunk = {"chunk_id": "ch00-001", "chapter": label, "text": TEXT3}
                path, sha = self.named_index(f"index.front-{position}.json", [chunk])
                rec = self.chapter_record(path, sha, [chunk], tag, TEXT3, ["s1"])
                result = self.one(rec)
                self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_appendix_number_never_resolves_a_chapter_tag(self):
        """``[Ch. 4]`` is chapter 4; ``Appendix 4`` is another chapter space."""
        appendix = {"chunk_id": "chA-004", "chapter": "Appendix 4", "text": TEXT3}
        path, sha = self.named_index("index.appendix-4.json", [appendix])
        rec = self.chapter_record(path, sha, [appendix], "[Ch. 4]", TEXT3, ["s1"])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_chapter_unmatched", codes(result))

        chapter = {"chunk_id": "ch04-001", "chapter": "4", "text": TEXT4}
        path, sha = self.named_index("index.appendix-4-both.json", [chapter, appendix])
        rec = self.chapter_record(path, sha, [chapter, appendix], "[Ch. 4]", TEXT3, ["s2"])
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_newlines_are_compared_literally_not_normalized(self):
        lf_quote = WRAPPED.replace("\r\n", "\n")
        rec = self.record(source_refs=[self.wrapped_ref()])
        rec = self.target(rec, answer=f'[Ch. 2] "{lf_quote}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_wrapped_quote_does_not_swallow_the_next_quote(self):
        answer = (
            f'[Ch. 2] "{WRAPPED}"\n'
            '[Ch. 2] "Invented after a wrapped quote."'
        )
        rec = self.record(source_refs=[self.wrapped_ref()])
        rec = self.target(rec, answer=answer)
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_ordinary_quoted_term_is_not_a_book_quote(self):
        rec = self.target(
            self.record(),
            answer='The book calls this "a magic marker" and moves on.',
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "PASS", result["findings"])

    def test_two_quote_lines_are_checked_independently(self):
        rec = self.target(
            self.record(),
            answer=f'[Ch. 1] "{QUOTE_SENTENCE}"\n[Ch. 1] "A second invented line."',
        )
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_quote_matching_is_literal_not_case_folded(self):
        lowered = QUOTE_SENTENCE[0].lower() + QUOTE_SENTENCE[1:]
        rec = self.target(self.record(), answer=f'[Ch. 1] "{lowered}"')
        result = self.one(rec)
        self.assertEqual(result["verdict"], "FAIL", result["findings"])
        self.assertIn("target_quote_not_in_source", codes(result))

    def test_gloss_needs_no_quote_but_a_declared_quote_is_checked(self):
        ok = self.target(
            self.record(), kind="gloss", answer="A progress marker.", citations=[]
        )
        self.assertEqual(self.one(ok)["verdict"], "PASS")
        bad = self.target(
            self.record(), kind="gloss", answer='[Ch. 1] "invented"', citations=[]
        )
        self.assertEqual(self.one(bad)["verdict"], "FAIL")


class CliTest(Fixture):
    def run_cli(self, *args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = DI.main([str(a) for a in args])
        return code, json.loads(buffer.getvalue())

    def test_exit_zero_on_pass(self):
        path = self.dataset_file("pass.jsonl", [self.record()])
        code, report = self.run_cli("--dataset", path, "--train-corpus", self.corpus)
        self.assertEqual(code, 0)
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["counts"]["records"], 1)

    def test_exit_one_on_unresolved_review(self):
        path = self.dataset_file("review.jsonl", [self.record()])
        code, report = self.run_cli("--dataset", path)
        self.assertEqual(code, 1)
        self.assertEqual(report["verdict"], "REVIEW")
        self.assertEqual(report["lineage"]["status"], "unknown")

    def test_exit_two_on_fail(self):
        path = self.dataset_file(
            "fail.jsonl",
            [self.record(source_refs=[self.source(chapter="2")])],
        )
        code, report = self.run_cli("--dataset", path, "--train-corpus", self.corpus)
        self.assertEqual(code, 2)
        self.assertEqual(report["verdict"], "FAIL")

    def test_multiple_datasets_are_checked_together_for_leakage(self):
        train = self.dataset_file("train.jsonl", [self.record(id="t", split="train")])
        dev = self.dataset_file("dev.jsonl", [self.record(id="d", split="dev")])
        code, report = self.run_cli("--dataset", train, "--dataset", dev)
        self.assertEqual(code, 2)
        self.assertEqual(report["counts"]["records"], 2)
        self.assertEqual(len(report["datasets"]), 2)
        self.assertIn("family_split_leak", codes(report["records"][1]))

    def test_missing_dataset_file_is_a_failure_not_an_empty_pass(self):
        code, report = self.run_cli("--dataset", self.tmp / "nope.jsonl")
        self.assertEqual(code, 2)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["counts"]["records"], 0)
        self.assertIn("dataset_missing", {f["code"] for f in report["findings"]})

    def test_report_is_stable_and_comparable_across_runs(self):
        path = self.dataset_file("stable.jsonl", [self.record()])
        first = self.run_cli("--dataset", path, "--train-corpus", self.corpus)[1]
        second = self.run_cli("--dataset", path, "--train-corpus", self.corpus)[1]
        for key in ("validator", "verdict", "counts", "lineage", "integrity"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["records"], second["records"])

    def test_verify_origins_flags_a_stale_origin_hash(self):
        path = self.dataset_file("origin.jsonl", [self.record()])
        code, report = self.run_cli(
            "--dataset", path, "--train-corpus", self.corpus, "--verify-origins"
        )
        self.assertEqual(code, 0, report)
        rec = self.record()
        rec["origin"]["sha256"] = "a" * 64
        self.sign(rec)
        bad = self.dataset_file("origin-bad.jsonl", [rec])
        code, report = self.run_cli(
            "--dataset", bad, "--train-corpus", self.corpus, "--verify-origins"
        )
        self.assertEqual(code, 2)
        self.assertIn("origin_stale", codes(report["records"][0]))


if __name__ == "__main__":
    unittest.main()
