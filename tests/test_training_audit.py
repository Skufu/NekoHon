"""Training-data audit: source truth, split safety, and the review queue.

These tests use only temporary fixtures: two tiny indexes, synthetic message
rows in the shipped fine-tune shape, and canonical schema-v1 records. They
never load `data/`, never call the engine, a model, an embedder, or a judge.

Public seam: `audit_records(records, index_paths=...)` and
`audit_files(paths, out_dir=..., index_paths=...)` in
`artifacts/harnesses/training_audit.py`. The CLI is `main(argv)`.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "harnesses"))

import training_audit as TA  # noqa: E402
import store  # noqa: E402

REFUSAL = "Not in this book."

TEXT_A1 = "Alpha is the first letter of the Greek alphabet."
TEXT_A2 = "Beta is the second letter of the Greek alphabet."
TEXT_A3 = "Gamma is the third letter of the Greek alphabet."
TEXT_B1 = "Raft achieves consensus through an elected leader."
TEXT_CURLY = "The book calls it \u201cdata about data\u201d."


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_index(path, book_id, chunks, figures=None):
    path = Path(path).with_suffix(".sqlite")
    payload = {
        "book_id": book_id,
        "chunks": [
            {
                "chunk_id": chunk_id,
                "chapter": "1",
                "heading": text.split(".", 1)[0],
                "section": "Chapter 1. Test",
                "text": text,
            }
            for chunk_id, text in chunks.items()
        ],
        "figures": figures or [],
    }
    store.write_index(path, payload)
    return path


def source_ref(index_path, book_id, chunk_id, text, role=None, kind="chunk"):
    ref = {
        "source_id": f"{book_id}:{index_path}:{chunk_id}",
        "book_id": book_id,
        "index_path": str(index_path),
        "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "chunk_id": chunk_id,
        "chapter": "1",
        "text_sha256": sha(text),
        "spans": [{"start": 0, "end": len(text), "text": text}],
        "kind": kind,
    }
    if role:
        ref["role"] = role
    return ref


def canonical(
    index_path,
    record_id,
    split,
    family,
    question,
    chunk_id,
    text,
    answer,
    *,
    role=None,
    paraphrase_of=None,
    kind="answer",
):
    ref = source_ref(index_path, "book-a", chunk_id, text, role=role)
    fact = {
        "claim": f"The passage says: {text}",
        "source_ids": [ref["source_id"]],
    }
    record = {
        "schema_version": 1,
        "id": record_id,
        "family_id": family,
        "split": split,
        "book_id": "book-a",
        "question": question,
        "history": [],
        "provided_source_ids": [ref["source_id"]],
        "source_refs": [ref],
        "expected": {
            "book_answerable": kind != "refusal",
            "evidence_sufficient": True,
            "allowed_behaviors": ["refuse"] if kind == "refusal" else ["answer"],
            "required_facts": [] if kind == "gloss" else [fact],
            "unsupported_claims": [],
        },
        "review": {
            "status": "needs_review",
            "author": "test",
            "reviewer": None,
            "notes": "fixture",
            "provenance": "agent",
        },
        "origin": {
            "path": str(index_path),
            "sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "record": chunk_id,
            "kind": "authored",
        },
        "target": {
            "answer": answer,
            "refused": answer == REFUSAL,
            "kind": kind,
            "citations": [] if kind == "refusal" else [ref["source_id"]],
        },
    }
    if paraphrase_of:
        record["metadata"] = {"paraphrase_of": [paraphrase_of]}
    return record


def messages_row(question, passages, answer, meta=None, history=None):
    blocks = "\n\n".join(
        f"[Ch. {chapter}] chunk_id={chunk_id}\n{text}"
        for chapter, chunk_id, text in passages
    )
    user = ""
    if history:
        user += f"Earlier in this conversation (not a source \u2014 do not quote it):\n{history}\n\n"
    user += f"Question: {question}\n\nPassages:\n{blocks}"
    return {
        "messages": [
            {"role": "system", "content": "Answer only from the passages."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ],
        "meta": meta or {"split": "train", "source": "test"},
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.index = write_index(
            self.root / "index.sqlite",
            "book-a",
            {"ch01-001": TEXT_A1, "ch01-002": TEXT_A2, "ch01-003": TEXT_A3},
        )

    def audit(self, records):
        return TA.audit_records(records, index_paths=[self.index], dataset_name="fixture")


class SplitSafetyTest(Base):
    def test_good_disjoint_records_pass_split_check(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev = canonical(
            self.index, "r-dev", "dev", "fam-b", "What is beta?", "ch01-002", TEXT_A2,
            f'[Ch. 1] "{TEXT_A2}"\nBeta is the second letter.',
        )
        result = self.audit([train, dev])
        self.assertEqual(result["split_findings"], [])
        self.assertEqual(result["summary"]["rows"], 2)
        self.assertEqual(result["summary"]["mechanical_pass"], 2)

    def test_duplicate_full_input_across_splits_fails(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev = json.loads(json.dumps(train))
        dev["id"] = "r-dev"
        dev["split"] = "dev"
        result = self.audit([train, dev])
        codes = {finding["code"] for finding in result["split_findings"]}
        self.assertIn("duplicate_full_input_cross_split", codes)

    def test_paraphrase_group_across_splits_fails(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev = canonical(
            self.index, "r-dev", "dev", "fam-b", "Define alpha in another way.", "ch01-002", TEXT_A2,
            f'[Ch. 1] "{TEXT_A2}"\nBeta is the second letter.',
            paraphrase_of="r-train",
        )
        result = self.audit([train, dev])
        codes = {finding["code"] for finding in result["split_findings"]}
        self.assertIn("paraphrase_cross_split", codes)

    def test_exact_question_across_splits_fails(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev = canonical(
            self.index, "r-dev", "dev", "fam-b", "What is alpha?", "ch01-002", TEXT_A2,
            f'[Ch. 1] "{TEXT_A2}"\nBeta is the second letter.',
        )
        result = self.audit([train, dev])
        codes = {finding["code"] for finding in result["split_findings"]}
        self.assertIn("question_cross_split", codes)

    def test_support_source_across_splits_fails(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev = canonical(
            self.index, "r-dev", "dev", "fam-b", "Tell me about alpha again.", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        result = self.audit([train, dev])
        codes = {finding["code"] for finding in result["split_findings"]}
        self.assertIn("support_cross_split", codes)

    def test_distractor_only_overlap_is_tracked_not_failed(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
            role=None,
        )
        # The distractor is provided to the train row but no fact uses it.
        train["source_refs"].append(
            source_ref(self.index, "book-a", "ch01-003", TEXT_A3, role="distractor")
        )
        train["provided_source_ids"].append(train["source_refs"][-1]["source_id"])
        dev = canonical(
            self.index, "r-dev", "dev", "fam-b", "What is gamma?", "ch01-003", TEXT_A3,
            f'[Ch. 1] "{TEXT_A3}"\nGamma is the third letter.',
        )
        result = self.audit([train, dev])
        self.assertEqual(result["split_findings"], [])
        overlap_keys = {item["key"] for item in result["context_overlaps"]}
        self.assertIn("book-a:ch01-003", overlap_keys)


class QuoteAndTargetTest(Base):
    def test_quote_matching_two_provided_blocks_marks_both_as_support(self):
        shared = "The overlapping sentence appears in both passages."
        index = write_index(
            self.root / "overlap.json",
            "book-a",
            {
                "ch01-001": shared + " First tail.",
                "ch01-002": shared + " Second tail.",
            },
        )
        row = messages_row(
            "What overlaps?",
            [
                ("1", "ch01-001", shared + " First tail."),
                ("1", "ch01-002", shared + " Second tail."),
            ],
            f'[Ch. 1] "{shared}"',
        )
        result = TA.audit_records([row], index_paths=[index], dataset_name="fixture")
        entry = result["entries"][0]
        self.assertEqual(set(entry["support_keys"]), {"book-a:ch01-001", "book-a:ch01-002"})
        self.assertEqual(entry["context_keys"], [])

    def test_quote_free_gloss_is_not_missing_quote(self):
        gloss = canonical(
            self.index, "r-gloss", "dev", "fam-a", "Explain alpha.", "ch01-001", TEXT_A1,
            "Alpha is the first letter in the Greek alphabet.",
            kind="gloss",
        )
        result = self.audit([gloss])
        entry = result["entries"][0]
        self.assertTrue(entry["target"]["quote_free_gloss"])
        self.assertEqual(entry["target"]["kind"], "gloss")
        self.assertEqual(entry["mechanical_status"], "PASS")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertNotIn("missing_quote", codes)
        self.assertNotIn("answer_without_quote", codes)

    def test_literal_canonical_target_is_still_queued_for_review(self):
        record = canonical(
            self.index, "r-answer", "dev", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"',
        )
        record["expected"]["required_facts"] = []
        result = self.audit([record])
        entry = result["entries"][0]
        self.assertEqual(entry["mechanical_status"], "PASS")
        self.assertEqual(entry["semantic_status"], "REVIEW_NOT_CERTIFIED")
        queue_ids = {item["id"] for item in result["review_queue"]}
        self.assertIn("r-answer", queue_ids)

    def test_prompt_only_canonical_row_is_not_an_unquoted_answer(self):
        record = canonical(
            self.index, "r-eval", "dev", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            "",
        )
        record.pop("target")
        result = self.audit([record])
        entry = result["entries"][0]
        self.assertEqual(entry["mechanical_status"], "PASS")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertNotIn("answer_without_quote", codes)
        self.assertIn("prompt_only_no_target", codes)

    def test_short_literal_quote_passes_and_forged_quote_fails(self):
        index = write_index(self.root / "water.json", "book-a", {"ch01-001": "Water is wet. It flows downhill."})
        good = messages_row(
            "Is water wet?",
            [("1", "ch01-001", "Water is wet. It flows downhill.")],
            '[Ch. 1] "Water is wet."',
        )
        bad = messages_row(
            "Is water wet?",
            [("1", "ch01-001", "Water is wet. It flows downhill.")],
            '[Ch. 1] "Water is dry."',
        )
        result = TA.audit_records([good, bad], index_paths=[index], dataset_name="fixture")
        self.assertEqual(result["entries"][0]["mechanical_status"], "PASS")
        self.assertEqual(result["entries"][1]["mechanical_status"], "FAIL")
        codes = {issue["code"] for issue in result["entries"][1]["issues"]}
        self.assertIn("target_quote_not_in_book", codes)

    def test_literal_normalized_and_absent_quotes_are_distinct(self):
        row = messages_row(
            "What is data about data?",
            [("1", "ch01-001", TEXT_CURLY)],
            '[Ch. 1] "The book calls it \u201cdata about data\u201d."\n'
            '[Ch. 1] "The book calls it "data about data"."\n'
            '[Ch. 1] "The book calls it "metadata"."',
        )
        result = self.audit([row])
        statuses = [check["status"] for check in result["entries"][0]["quote_checks"]]
        self.assertIn("literal", statuses)
        self.assertIn("normalized_only", statuses)
        self.assertIn("absent_book", statuses)
        self.assertEqual(result["entries"][0]["mechanical_status"], "FAIL")

    def test_intentional_withheld_refusal_is_not_junk(self):
        row = messages_row(
            "What is the capital of France?",
            [("1", "ch01-001", TEXT_A1)],
            REFUSAL,
        )
        result = self.audit([row])
        entry = result["entries"][0]
        self.assertTrue(entry["target"]["refusal_exact"])
        self.assertEqual(entry["refusal_check"]["classification"], "terms_absent_from_supplied_context")
        self.assertFalse(entry["refusal_check"]["junk"])
        self.assertEqual(entry["mechanical_status"], "PASS")

    def test_refusal_with_commentary_fails(self):
        row = messages_row(
            "What is the capital of France?",
            [("1", "ch01-001", "Water is wet. It flows downhill.")],
            "Not in this book. The passage says otherwise.",
        )
        result = self.audit([row])
        entry = result["entries"][0]
        self.assertFalse(entry["target"]["refusal_exact"])
        self.assertEqual(entry["mechanical_status"], "FAIL")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertIn("refusal_with_commentary", codes)


class ResolutionTest(Base):
    def test_canonical_synthetic_source_is_legitimate_not_missing_book(self):
        quote = "A consensus leader coordinates a replicated log."
        record = canonical(
            self.index, "r-synthetic", "dev", "fam-syn", "What is consensus?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{quote}"',
        )
        ref = record["source_refs"][0]
        ref.update(
            {
                "source_id": "synthetic-domain:ds01-001",
                "book_id": "synthetic-domain",
                "index_path": "synthetic://distributed-systems",
                "chunk_id": "ds01-001",
                "kind": "synthetic",
                "text_sha256": sha(quote),
                "spans": [{"start": 0, "end": len(quote), "text": quote}],
            }
        )
        record["provided_source_ids"] = [ref["source_id"]]
        record["expected"]["required_facts"][0]["source_ids"] = [ref["source_id"]]
        result = TA.audit_records([record], index_paths=[self.index], dataset_name="fixture")
        entry = result["entries"][0]
        self.assertEqual(entry["source_bindings"][0]["resolution"], "synthetic")
        self.assertEqual(entry["mechanical_status"], "PASS")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertIn("canonical_synthetic_source", codes)
        self.assertNotIn("source_ref_unresolved", codes)

    def test_caption_source_is_auditable(self):
        caption = "A watermark advances with event time."
        index = write_index(
            self.root / "caption.json",
            "book-a",
            {"ch01-001": TEXT_A1},
            figures=[{"figure_id": "figure-1-1", "caption": caption}],
        )
        record = canonical(
            index, "r-caption", "dev", "fam-cap", "What does the figure show?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{caption}"',
        )
        ref = record["source_refs"][0]
        ref.update(
            {
                "source_id": "book-a:caption:figure-1-1",
                "kind": "caption",
                "figure_id": "figure-1-1",
                "chunk_id": "figure-1-1",
                "text_sha256": sha(caption),
                "spans": [{"start": 0, "end": len(caption), "text": caption}],
            }
        )
        record["provided_source_ids"] = [ref["source_id"]]
        record["expected"]["required_facts"][0]["source_ids"] = [ref["source_id"]]
        result = TA.audit_records([record], index_paths=[index], dataset_name="fixture")
        entry = result["entries"][0]
        self.assertEqual(entry["source_bindings"][0]["resolution"], "verbatim")
        self.assertEqual(entry["quote_checks"][0]["status"], "literal")
        self.assertEqual(entry["mechanical_status"], "PASS")

    def test_book_id_resolved_by_text_not_assumed(self):
        book_a = write_index(self.root / "a.json", "book-a", {"ch01-001": TEXT_A1})
        book_b = write_index(self.root / "b.json", "book-b", {"ch01-001": TEXT_B1})
        row = messages_row(
            "What is Raft?",
            [("1", "ch01-001", TEXT_B1)],
            f'[Ch. 1] "{TEXT_B1}"',
        )
        result = TA.audit_records([row], index_paths=[book_a, book_b], dataset_name="fixture")
        binding = result["entries"][0]["source_bindings"][0]
        self.assertEqual(binding["book_id"], "book-b")
        self.assertEqual(binding["resolution"], "verbatim")
        self.assertEqual(result["entries"][0]["mechanical_status"], "PASS")

    def test_formatting_drift_resolves_when_chunk_id_collides(self):
        book_a = write_index(self.root / "a.json", "book-a", {"ch01-001": "Alpha | Beta\nGamma | Delta"})
        book_b = write_index(self.root / "b.json", "book-b", {"ch01-001": "Raft | Leader\nFollower | Term"})
        row = messages_row(
            "What is Raft?",
            [("1", "ch01-001", "Raft Leader\r\nFollower Term")],
            '[Ch. 1] "Raft Leader"',
        )
        result = TA.audit_records([row], index_paths=[book_a, book_b], dataset_name="fixture")
        binding = result["entries"][0]["source_bindings"][0]
        self.assertEqual(binding["book_id"], "book-b")
        self.assertEqual(binding["resolution"], "formatting_drift")

    def test_synthetic_domain_is_not_a_missing_book(self):
        row = messages_row(
            "What is Raft consensus?",
            [("1", "ds01-001", TEXT_B1)],
            f'[Ch. 1] "{TEXT_B1}"',
            meta={"split": "train", "source": "cross-book", "domain": "Distributed Systems"},
        )
        result = self.audit([row])
        entry = result["entries"][0]
        binding = entry["source_bindings"][0]
        self.assertEqual(binding["resolution"], "synthetic")
        self.assertEqual(entry["mechanical_status"], "PASS")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertNotIn("source_unresolved", codes)

    def test_formatting_drift_is_review_not_fabricated(self):
        index = write_index(
            self.root / "drift.json",
            "book-a",
            {"ch01-001": "Alpha | Beta\nGamma | Delta"},
        )
        row = messages_row(
            "What are the labels?",
            [("1", "ch01-001", "Alpha Beta\r\nGamma Delta")],
            '[Ch. 1] "Alpha Beta"',
        )
        result = TA.audit_records([row], index_paths=[index], dataset_name="fixture")
        entry = result["entries"][0]
        binding = entry["source_bindings"][0]
        self.assertEqual(binding["resolution"], "formatting_drift")
        self.assertEqual(entry["mechanical_status"], "REVIEW")
        codes = {issue["code"] for issue in entry["issues"]}
        self.assertIn("source_formatting_drift", codes)
        self.assertNotIn("target_quote_not_in_book", codes)


class SemanticReviewBindingTest(Base):
    def make_source(self, answer=None, text=TEXT_A1):
        row = messages_row(
            "What is alpha?",
            [("1", "ch01-001", text)],
            answer or f'[Ch. 1] "{TEXT_A1}"',
            meta={"split": "train", "source": "test"},
        )
        source = self.root / "rows.jsonl"
        source.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
        return source

    def make_review(self, source, entry, *, messages_hash=None, start=None, end=None, text=None, status="accepted", claims=True, verdict="supported"):
        raw = source.read_bytes().split(b"\n")[0]
        user = json.loads(raw)["messages"][1]["content"]
        start = user.find(TEXT_A1) if start is None else start
        end = start + len(TEXT_A1) if end is None else end
        target_claims = []
        if claims:
            target_claims = [
                {
                    "claim": text or TEXT_A1,
                    "verdict": verdict,
                    "witnesses": [
                        {
                            "message_index": 1,
                            "start": start,
                            "end": end,
                            "text": text or user[start:end],
                            "role": "provided_source",
                        }
                    ],
                }
            ]
        review = {
            "id": entry["id"],
            "origin": {
                "path": str(source),
                "sha256": hashlib.sha256(raw + b"\n").hexdigest(),  # full physical line including LF
                "record": 1,
                "line_sha256": hashlib.sha256(raw).hexdigest(),  # without LF
            },
            "messages_sha256": messages_hash or entry["messages_sha256"],
            "user_prompt_sha256": entry["user_prompt_sha256"],
            "target_sha256": entry["target_sha256"],
            "review": {
                "status": status,
                "reviewer": "independent-test",
                "provenance": "agent",
                "criteria_version": "training-target-source-v1",
                "notes": "fixture",
            },
            "target_claims": target_claims,
            "issues": [],
            "task_kind": "definition",
            "source_scope": "user message_index=1 provided passages only",
        }
        path = self.root / "review.jsonl"
        path.write_text(json.dumps(review) + "\n", encoding="utf-8")
        return path

    def run_with_review(self, source, review, expected_sha256=None):
        item = {"path": str(review), "shard": "A"}
        if expected_sha256:
            item["expected_sha256"] = expected_sha256
        return TA.audit_files(
            [{"path": str(source), "role": "historical_train", "id_prefix": "x3"}],
            index_paths=[str(self.index)],
            semantic_review_paths=[item],
        )

    def test_semantic_decision_binds_only_after_hashes_and_witnesses(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        entry = base["entries"][0]
        review = self.make_review(source, entry)
        result = self.run_with_review(source, review)
        bound = result["entries"][0]
        self.assertEqual(bound["semantic_review"]["decision"], "accepted")
        self.assertEqual(bound["semantic_review"]["binding_status"], "BOUND")
        self.assertTrue(bound["semantic_review"]["witnesses"]["valid"] >= 1)
        self.assertEqual(bound["origin"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(
            bound["origin"]["line_sha256_with_lf"],
            hashlib.sha256(source.read_bytes().split(b"\n")[0] + b"\n").hexdigest(),
        )
        self.assertEqual(bound["semantic_status"], "SEMANTIC_REVIEW_A_ACCEPTED_PENDING_CANONICAL_BIND")
        self.assertEqual(bound["semantic_review"]["canonical_binding"]["status"], "PENDING_INDEPENDENT_FINAL_BIND")
        self.assertFalse(bound["train_ready"])

    def test_full_file_origin_dialect_binds_without_overwriting_canonical_origin(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        entry = base["entries"][0]
        review = self.make_review(source, entry)
        payload = json.loads(review.read_text())
        payload["origin"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        review.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "BOUND")
        self.assertEqual(bound["semantic_review"]["hash_binding"]["origin_dialect"], "full_file")
        self.assertEqual(bound["origin"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(bound["semantic_review"]["hash_binding"]["full_file_sha256"], bound["origin"]["sha256"])

    def test_hash_mismatch_does_not_transfer_a_decision(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0], messages_hash="0" * 64)
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "INVALID")
        self.assertEqual(bound["semantic_status"], "SEMANTIC_REVIEW_BINDING_FAILED")
        self.assertIn("semantic_review_hash_mismatch", {issue["code"] for issue in bound["issues"]})

    def test_witness_offset_mismatch_does_not_transfer_a_decision(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0], start=0, end=5, text="wrong")
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "INVALID")
        self.assertIn("semantic_review_witness_invalid", {issue["code"] for issue in bound["issues"]})

    def test_accepted_nonrefusal_without_claims_is_not_bound(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0], claims=False)
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "INVALID")
        self.assertEqual(bound["semantic_status"], "SEMANTIC_REVIEW_BINDING_FAILED")
        self.assertIn("accepted_non_refusal_without_claims", {issue["code"] for issue in bound["issues"]})

    def test_accepted_nonrefusal_without_supported_verdict_is_not_bound(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0], verdict="ambiguous")
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "INVALID")
        self.assertIn("accepted_non_refusal_without_supported_witness", {issue["code"] for issue in bound["issues"]})

    def test_accepted_exact_refusal_without_claims_is_valid(self):
        source = self.make_source(answer=REFUSAL)
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0], claims=False)
        bound = self.run_with_review(source, review)["entries"][0]
        self.assertEqual(bound["semantic_review"]["binding_status"], "BOUND")
        self.assertEqual(bound["semantic_status"], "SEMANTIC_REVIEW_A_ACCEPTED_PENDING_CANONICAL_BIND")

    def test_expected_review_ledger_hash_mismatch_fails_closed(self):
        source = self.make_source()
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        review = self.make_review(source, base["entries"][0])
        bound = self.run_with_review(source, review, expected_sha256="0" * 64)["entries"][0]
        self.assertEqual(bound.get("semantic_review", {}).get("binding_status"), "INVALID")
        self.assertEqual(bound["semantic_status"], "SEMANTIC_REVIEW_BINDING_FAILED")
        self.assertIn("review_ledger_hash_mismatch", {issue["code"] for issue in bound["issues"]})

    def test_normalized_quote_stages_unapplied_exact_restoration(self):
        source_text = "On the other extreme, cold data is infrequently accessed data."
        source = self.make_source(answer='[Ch. 1] "Cold data is infrequently accessed data."', text=source_text)
        base = TA.audit_files([{"path": str(source), "role": "historical_train", "id_prefix": "x3"}], index_paths=[str(self.index)])
        entry = base["entries"][0]
        raw = source.read_bytes().split(b"\n")[0]
        user = json.loads(raw)["messages"][1]["content"]
        exact = "cold data is infrequently accessed data."
        start = user.find(exact)
        review = self.make_review(source, entry, start=start, end=start + len(exact), text=exact)
        bound = self.run_with_review(source, review)["entries"][0]
        repair = bound["semantic_review"]["mechanical_repair"]
        self.assertEqual(repair["kind"], "quote_exact_restoration")
        self.assertFalse(repair["applied"])
        self.assertTrue(repair["peer_rebind_required"])
        self.assertEqual(repair["after_text"], exact)


class CandidateBuilderTest(unittest.TestCase):
    def entry(self, entry_id, line, messages, support, *, decision="accepted", issues=None, kind="answer", context=None, family=None, question=None, role="historical_train"):
        return {
            "id": entry_id,
            "line": line,
            "role": role,
            "messages_sha256": messages,
            "target_sha256": f"target-{entry_id}",
            "semantic_review": {"decision": decision, "binding_status": "BOUND", "task_kind": "definition", "notes": "fixture"} if role == "historical_train" else {},
            "mechanical_status": "PASS",
            "issues": issues or [],
            "target": {"kind": kind},
            "support_keys": support,
            "context_keys": context or [],
            "source_scope": ["book-a"],
            "question": question or f"Question {entry_id}?",
            "family_id": family or f"family:{entry_id}",
            "component_id": None,
        }

    def test_candidate_dedups_inputs_and_records_every_exclusion(self):
        entries = [
            self.entry("r1", 1, "same-input", ["fde:ch01-001"]),
            self.entry("r2", 2, "same-input", ["fde:ch01-002"]),
            self.entry("r3", 3, "unique-3", ["fde:ch09-009"]),
            self.entry("r4", 4, "unique-4", ["fde:ch04-004"], decision="needs_review"),
            self.entry("r5", 5, "unique-5", ["fde:ch05-005"], issues=[{"code": "target_quote_normalized_only", "severity": "REVIEW"}]),
        ]
        dev = [{"support_keys": ["fde:ch09-009"], "context_keys": [], "question": "dev?"}]
        candidate = TA.build_candidate(entries, dev, {}, seed=7, validation_percent=100)
        self.assertEqual(candidate["manifest"]["counts"]["selected"], 1)
        self.assertEqual(candidate["manifest"]["counts"]["excluded"], 4)
        reasons = {row["id"]: row["exclusion_reason"] for row in candidate["ledger"] if not row["selected"]}
        self.assertEqual(reasons["r2"], "duplicate_complete_input")
        self.assertEqual(reasons["r3"], "dev_support_component_overlap")
        self.assertEqual(reasons["r4"], "semantic_needs_review")
        self.assertEqual(reasons["r5"], "target_quote_normalization_requires_repair")

    def test_candidate_resolves_semantic_warnings_but_not_source_identity(self):
        entries = [
            self.entry("r-refusal", 1, "input-1", ["fde:ch02-002"], kind="refusal", issues=[{"code": "refusal_with_context_terms", "severity": "REVIEW"}]),
            self.entry("r-gloss", 2, "input-2", ["fde:ch03-003"], kind="gloss", issues=[{"code": "quote_free_gloss", "severity": "INFO"}]),
            self.entry("r-drift", 3, "input-3", ["fde:ch04-004"], issues=[{"code": "source_formatting_drift", "severity": "REVIEW"}]),
        ]
        candidate = TA.build_candidate(entries, [], {}, seed=7, validation_percent=100)
        self.assertEqual(candidate["manifest"]["counts"]["selected"], 2)
        reasons = {row["id"]: row["exclusion_reason"] for row in candidate["ledger"] if not row["selected"]}
        self.assertEqual(reasons["r-drift"], "source_identity_repair_pending")
        resolved = candidate["manifest"]["warning_resolution"]["resolved_by_source_review"]
        self.assertIn("r-refusal", resolved["refusal_with_context_terms"])
        self.assertIn("r-gloss", resolved["quote_free_gloss"])
        ineligible = candidate["manifest"]["warning_resolution"]["still_mechanically_ineligible"]
        self.assertIn("r-drift", ineligible["source_formatting_drift"])

    def test_full_graph_component_bridges_and_dev_components_are_excluded(self):
        entries = [
            self.entry("h1", 1, "input-1", ["fde:ch01-001"], family="family-1"),
            self.entry("h2", 2, "input-2", ["fde:ch02-002"], family="family-2"),
            self.entry("bridge", 3, "input-3", ["fde:ch02-002"], decision="needs_review", family="family-1"),
            self.entry("h3", 4, "input-4", ["fde:ch04-004"], family="dev-family"),
        ]
        dev = [self.entry("dev", 1, "dev-input", ["fde:ch03-003"], role="dev", family="dev-family")]
        candidate = TA.build_candidate(entries, dev, {}, seed=7, validation_percent=100)
        by_id = {row["id"]: row for row in candidate["ledger"]}
        self.assertEqual(by_id["h1"]["fold"], by_id["h2"]["fold"])
        self.assertNotEqual(by_id["h1"]["full_component_id"], by_id["h2"]["candidate_component_id"])
        self.assertEqual(by_id["h3"]["exclusion_reason"], "dev_full_component_overlap")
        self.assertFalse(by_id["h3"]["selected"])
        self.assertFalse(candidate["manifest"]["ready_for_training"])
        self.assertTrue(candidate["manifest"]["prospective_eligible"])
        self.assertFalse(candidate["manifest"]["launchable"])

    def test_dev_exclusion_counts_components_and_rows_not_dict_keys(self):
        entries = [
            self.entry("s1", 1, "s1", ["dev:support"], family="s1"),
            self.entry("s2", 2, "s2", ["dev:support"], family="s2"),
            self.entry("c1", 3, "c1", ["fde:ch05-005"], context=["dev:context-1"], family="c1"),
            self.entry("c2", 4, "c2", ["fde:ch06-006"], context=["dev:context-2"], family="c2"),
        ]
        dev = [
            self.entry("dev-a", 1, "dev-a", ["dev:support"], role="dev", family="dev-family-a"),
            self.entry("dev-b", 2, "dev-b", [], context=["dev:context-1"], role="dev", family="dev-family-b"),
            self.entry("dev-c", 3, "dev-c", [], context=["dev:context-2"], role="dev", family="dev-family-c"),
        ]
        candidate = TA.build_candidate(entries, dev, {}, seed=7, validation_percent=100)
        separation = candidate["manifest"]["dev_separation"]
        self.assertEqual(separation["excluded_support_components"], 1)
        self.assertEqual(separation["excluded_support_rows"], 2)
        self.assertEqual(separation["excluded_context_components"], 2)
        self.assertEqual(separation["excluded_context_rows"], 2)

    def test_candidate_split_never_splits_a_support_component(self):
        entries = [
            self.entry("r1", 1, "input-1", ["fde:ch02-002"]),
            self.entry("r2", 2, "input-2", ["fde:ch02-002"]),
            self.entry("r3", 3, "input-3", ["fde:ch03-003"]),
        ]
        candidate = TA.build_candidate(entries, [], {}, seed=7, validation_percent=100)
        folds = {row["id"]: row["fold"] for row in candidate["ledger"] if row["selected"]}
        self.assertEqual(folds["r1"], folds["r2"])
        self.assertEqual(candidate["manifest"]["checks"]["support_key_cross_fold"], [])
        self.assertEqual(candidate["manifest"]["checks"]["full_component_cross_fold"], [])
        self.assertEqual(candidate["manifest"]["checks"]["candidate_component_cross_fold"], [])


class FileAuditTest(Base):
    def test_audit_files_writes_ledger_manifest_and_review_queue(self):
        row = messages_row(
            "What is alpha?",
            [("1", "ch01-001", TEXT_A1)],
            f'[Ch. 1] "{TEXT_A1}"',
        )
        source = self.root / "rows.jsonl"
        source.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
        before = source.read_bytes()
        out = self.root / "out"
        result = TA.audit_files([str(source)], out_dir=str(out), index_paths=[str(self.index)])
        self.assertEqual(source.read_bytes(), before)
        ledger = [json.loads(line) for line in (out / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["raw_line_sha256"], sha(json.dumps(row, separators=(",", ":"))))
        manifest = json.loads((out / "manifest.json").read_text())
        self.assertEqual(manifest["inputs"][0]["rows"], 1)
        self.assertEqual(manifest["semantic_certification"], "NOT CLAIMED")
        self.assertTrue((out / "review-queue.jsonl").is_file())

        code = TA.main(["--input", str(source), "--index", str(self.index), "--out", str(self.root / "out2")])
        self.assertEqual(code, 1)
        self.assertTrue((self.root / "out2" / "ledger.jsonl").is_file())

    def test_ledger_binds_origin_and_review_without_accepting(self):
        first = messages_row(
            "What is alpha?",
            [("1", "ch01-001", TEXT_A1)],
            f'[Ch. 1] "{TEXT_A1}"',
            meta={"split": "train", "source": "test"},
        )
        second = messages_row(
            "What is beta?",
            [("1", "ch01-002", TEXT_A2)],
            f'[Ch. 1] "{TEXT_A2}"',
            meta={"split": "train", "source": "test"},
        )
        source = self.root / "x3.jsonl"
        source.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in (first, second)) + "\n",
            encoding="utf-8",
        )
        result = TA.audit_files(
            [{"path": str(source), "role": "historical_train", "id_prefix": "x3", "shard_boundary": 1}],
            out_dir=str(self.root / "out"),
            index_paths=[str(self.index)],
        )
        entry = result["entries"][0]
        self.assertEqual(entry["id"], "x3-line-0001")
        self.assertEqual(entry["shard"], "A")
        self.assertEqual(entry["origin"]["record"], "1")
        self.assertEqual(entry["origin"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(entry["origin"]["line_sha256"], entry["raw_line_sha256"])
        self.assertEqual(entry["origin"]["path"], str(source))
        self.assertEqual(len(entry["user_prompt_sha256"]), 64)
        self.assertEqual(len(entry["messages_sha256"]), 64)
        self.assertEqual(len(entry["target_sha256"]), 64)
        self.assertEqual(entry["review"]["status"], "needs_review")
        self.assertEqual(entry["review"]["criteria_version"], "training-target-source-v1")
        self.assertFalse(entry["canonical_ready"])
        self.assertEqual(result["entries"][1]["shard"], "B")

    def test_baseline_selection_is_metadata_only(self):
        train = canonical(
            self.index, "r-train", "train", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            f'[Ch. 1] "{TEXT_A1}"\nAlpha is the first letter.',
        )
        dev_one = canonical(
            self.index, "dev-one", "dev", "fam-b", "What is beta?", "ch01-002", TEXT_A2,
            f'[Ch. 1] "{TEXT_A2}"\nBeta is the second letter.',
        )
        dev_two = canonical(
            self.index, "dev-two", "dev", "fam-c", "What is gamma?", "ch01-003", TEXT_A3,
            f'[Ch. 1] "{TEXT_A3}"\nGamma is the third letter.',
        )
        source = self.root / "dev.jsonl"
        original = "\n".join(json.dumps(row, separators=(",", ":")) for row in (train, dev_one, dev_two)) + "\n"
        source.write_text(original, encoding="utf-8")
        selection = self.root / "baseline-selection.json"
        selection.write_text(json.dumps({"ids": ["dev-one", "missing-id"]}), encoding="utf-8")
        result = TA.audit_files(
            [{"path": str(source), "role": "dev"}],
            out_dir=str(self.root / "out"),
            index_paths=[str(self.index)],
            baseline_selection_path=str(selection),
        )
        self.assertEqual(source.read_text(encoding="utf-8"), original)
        baseline = result["manifest"]["baseline_selection"]
        self.assertEqual(baseline["selected"], 2)
        self.assertEqual(baseline["found"], 1)
        self.assertEqual(baseline["missing"], ["missing-id"])
        by_id = {entry["id"]: entry for entry in result["entries"]}
        self.assertTrue(by_id["dev-one"]["baseline_selected"])
        self.assertFalse(by_id["dev-two"]["baseline_selected"])

    def test_dev_review_status_is_derived_from_the_primary_file(self):
        accepted = canonical(
            self.index, "dev-accepted", "dev", "fam-a", "What is alpha?", "ch01-001", TEXT_A1,
            "",
        )
        accepted.pop("target")
        accepted["review"]["status"] = "accepted"
        pending = canonical(
            self.index, "dev-pending", "dev", "fam-b", "What is beta?", "ch01-002", TEXT_A2,
            "",
        )
        pending.pop("target")
        source = self.root / "dev.jsonl"
        source.write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in (accepted, pending)) + "\n",
            encoding="utf-8",
        )
        result = TA.audit_files(
            [{"path": str(source), "role": "dev"}],
            index_paths=[str(self.index)],
            out_dir=str(self.root / "out"),
        )
        manifest = result["manifest"]
        self.assertEqual(manifest["dev_review_source"]["primary"][0]["review_status_counts"], {"accepted": 1, "needs_review": 1})
        self.assertIn("1 accepted, 1 needs_review", manifest["decisions"]["dev_86"])
        self.assertNotIn("all 86", " ".join(manifest["unknowns"]))
        self.assertTrue(any("author candidate" in decision for decision in manifest["decisions"].values()))

    def test_line_endings_are_recorded_and_not_rewritten(self):
        row = messages_row(
            "What is alpha?",
            [("1", "ch01-001", TEXT_A1)],
            f'[Ch. 1] "{TEXT_A1}"',
        )
        source = self.root / "rows.jsonl"
        payload = (json.dumps(row) + "\n").encode("utf-8")
        source.write_bytes(payload)
        before = source.read_bytes()
        result = TA.audit_files(
            [str(source)],
            out_dir=str(self.root / "out"),
            index_paths=[str(self.index)],
        )
        self.assertEqual(source.read_bytes(), before)
        info = result["manifest"]["inputs"][0]
        self.assertEqual(info["lf_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(info["line_endings"]["lf"], 1)
        self.assertEqual(info["line_endings"]["crlf"], 0)
        rebuilt = payload.replace(b"\n", b"\r\n")
        self.assertEqual(info["crlf_rejoined_sha256"], hashlib.sha256(rebuilt).hexdigest())


if __name__ == "__main__":
    unittest.main()
