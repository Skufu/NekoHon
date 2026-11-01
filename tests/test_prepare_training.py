"""The training-release gate must refuse, not warn.

Every test here creates a corpus and breaks exactly one thing. A gate that
passes a broken fixture is worse than no gate, because it would let a GPU run
on data that the repo has already mis-described once.

Nothing here touches the network, a model, or `data/`. The corpus is synthetic
and four rows long.
"""

import ast
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "colab"))

import prepare_training as PT  # noqa: E402

REFUSAL = "Not in this book."
TRAIN_Q = "what is a watermark in a stream processing system and how does it move"
CONTROL_NEAR = "what is a watermark in a stream processing system and how does it work"


def row(question, label, source="synthetic", asked=None):
    prompt = question if asked is None else asked
    user = "Question: %s?\n\nPassages:\n[Ch. 1] chunk_id=c1\nA passage." % prompt
    return {
        "messages": [
            {"role": "system", "content": "You answer only from the passages below."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": label},
        ],
        "meta": {"question": asked if asked is not None else question,
                 "asked": asked if asked is not None else question,
                 "source": source},
    }


class Fixture(unittest.TestCase):
    """One valid corpus, a parent, a review, a split and controls."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prep-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rows = [
            row(TRAIN_Q, '[Ch. 1] "A watermark is a threshold."\nIt marks progress.'),
            row("what is a batch pipeline and when is it used",
                '[Ch. 2] "Batch processing handles bounded data."\nIt runs on a schedule.'),
            row("what is a figure id in a caption", "Not in this book."),
            row("explain s3", "Amazon S3 is durable object storage.", source="gloss"),
        ]
        self.corpus = self.write_jsonl("corpus.jsonl", self.rows)
        self.parent = self.write_jsonl("parent.jsonl", self.rows[:1] + [
            row("what is a retired row", "Not in this book.")] + self.rows[1:])
        self.ledger, self.audit = self.frozen_split()
        self.runner = self.write_bytes("runner.py", b"# synthetic runner\nprint('run')\n")
        self.deps = self.write_bytes("deps.py", b"# synthetic deps\nprint('deps')\n")
        self.review = None
        self.review_written = self.write_json("review.json", {
            "status": "accepted", "reviewer": "reviewer-a",
            "criteria_version": "source-v1", "rows": len(self.rows)})
        self.control = self.write_jsonl("control.jsonl", [
            {"id": "c1", "question": "how does a vacuum cleaner work"},
            {"id": "c2", "question": "what is a data lake"},
        ])
        self.locked = self.write_jsonl("locked.jsonl", [{"opaque": True}])
        self.legacy = self.write_jsonl("legacy.jsonl", [{"id": "l1", "question": "legacy dev ask"}])
        self.locked_hashes = [PT.sha256_bytes(b"reserved-question-1"),
                              PT.sha256_bytes(b"reserved-question-2")]
        self.out = self.tmp / "out"

    # -- builders -------------------------------------------------------
    def write_bytes(self, name, data):
        path = self.tmp / name
        path.write_bytes(data)
        return path

    def write_jsonl(self, name, rows, crlf=False):
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        data = text.encode("utf-8")
        return self.write_bytes(name, PT.crlf_bytes(data) if crlf else data)

    def write_json(self, name, obj):
        path = self.tmp / name
        path.write_text(json.dumps(obj, indent=1), encoding="utf-8")
        return path

    findings = []

    def frozen_split(self, rows=None, corpus=None, overrides=None):
        """A stand-in for the corpus worker's ledger + audit manifest."""
        rows = rows or self.rows
        corpus = corpus or self.corpus
        overrides = overrides or {}
        entries = []
        for index in range(len(rows)):
            entry = {"id": "row-%d" % index,
                     "source_path": str(corpus), "line": index + 1, "split": "train",
                     "family_id": "question:%d" % index,
                     "component_id": "component:%d" % index,
                     "role": "derived_historical_train", "train_ready": True}
            entry.update(overrides.get(index) or {})
            entries.append(entry)
        ledger = self.write_bytes("ledger.jsonl",
                                  ("\n".join(json.dumps(e) for e in entries) + "\n").encode())
        audit = self.write_json("audit-manifest.json", {
            "audit": "training_audit", "semantic_certification": "NOT CLAIMED",
            "config": {"random_assignment": "none", "seed": 20261029,
                       "split_policy": "connected components over exact question, family, "
                                       "actual answer-support source, history referent, "
                                       "duplicate full input; whole components only"},
            "split_findings": self.findings,
            "exposure": {"dev_vs_777": {
                "dev_support_exposed": 1, "dev_context_seen": 0, "dev_source_unseen": 2,
                "support_exposed_ids": ["dev-source-1"],
                "context_seen_ids": [],
                "exact_question_ids": ["dev-question-1"]}}})
        return ledger, audit

    def binds(self, spec):
        split = PT.verify_frozen_split(self.rows, spec, PT.Report())
        return {
            "dataset_sha256": PT.sha256_bytes(self.corpus.read_bytes()),
            "rows": len(self.rows),
            "recipe_sha256": PT.sha256_bytes(PT.canonical_json(spec["recipe"]).encode()),
            "ledger_sha256": split["sha256_ledger"],
            "audit_manifest_sha256": split["sha256_audit"],
            "exposure": split["exposure"],
            "exposure_ids_sha256": PT.sha256_bytes(
                "\n".join(sorted(["support:dev-source-1", "question:dev-question-1"])
                          ).encode("utf-8")),
            "tokenizer_config_sha256": spec["recipe"]["tokenizer_config_sha256"],
            "runner_sha256": PT.sha256_bytes(spec["runner"]["path"] and
                                            Path(spec["runner"]["path"]).read_bytes()),
            "deps_sha256": PT.sha256_bytes(Path(spec["runner"]["deps"]).read_bytes()),
        }

    def locked_control(self, **overrides):
        entry = {
            "name": "locked", "path": str(self.locked), "role": "reserved",
            "sha256": PT.sha256_bytes(self.locked.read_bytes()),
            "questions_count": len(self.locked_hashes),
            "questions_sha256": list(self.locked_hashes),
            "list_sha256": PT.sha256_bytes(
                "\n".join(sorted(self.locked_hashes)).encode("utf-8")),
            "attestation": {"reviewer": "reviewer-a", "complete": True,
                            "method": "hashes extracted read-only; no text supplied"},
        }
        entry.update(overrides)
        return entry

    def spec(self, **overrides):
        review_override = overrides.pop("source_review", None)
        spec = {
            "schema": PT.SCHEMA,
            "status": "certified",
            "release_id": "test-release",
            "dataset": {
                "path": str(self.corpus),
                "sha256_bytes": PT.sha256_bytes(self.corpus.read_bytes()),
                "sha256_rows": PT.corpus_digest(self.rows),
                "rows": len(self.rows),
                "refusals": 1,
                "line_ending": "lf",
                "question_paths": ["meta.question", "meta.asked"],
                "label_path": "messages[-1].content",
                "allow_untagged_sources": ["gloss"],
                "allowed_duplicate_rows": 0,
            },
            "lineage": [{"path": str(self.parent),
                         "sha256_bytes": PT.sha256_bytes(self.parent.read_bytes()),
                         "relation": "order_preserving_subset",
                         "removed_rows": {"cited": 0, "refusal": 1}}],
            "source_review": {
                "path": str(self.review_written), "sha256": "",
                "status": "accepted", "reviewer": "reviewer-a",
                "criteria_version": "source-v1", "binds": {}},
            "frozen_split": {
                "ledger": str(self.ledger), "manifest": str(self.audit),
                "sha256_ledger": PT.sha256_bytes(self.ledger.read_bytes()),
                "sha256_audit": PT.sha256_bytes(self.audit.read_bytes()),
                "role": "derived_historical_train", "exposure_key": "dev_vs_777"},
            "accepted_exposure": {"dev_support_exposed": 1, "dev_context_seen": 0,
                                  "dev_source_unseen": 2},
            "accepted_split_findings": [],
            "required_controls": ["locked"],
            "evaluation_controls": [
                {"name": "control", "path": str(self.control),
                 "sha256": PT.sha256_bytes(self.control.read_bytes()), "reserved": False},
                self.locked_control(),
                {"name": "legacy", "path": str(self.legacy), "role": "development",
                 "sha256": PT.sha256_bytes(self.legacy.read_bytes())},
            ],
            "expected_seen_collisions": [],
            "runner": {"path": str(self.runner), "deps": str(self.deps),
                       "sha256": PT.sha256_bytes(self.runner.read_bytes()),
                       "deps_sha256": PT.sha256_bytes(self.deps.read_bytes()),
                       "consumes_frozen_inputs": True, "preflight_gate": True},
            "recipe": {
                "base_model": "org/model", "base_revision": "a" * 40,
                "tokenizer_revision": "b" * 40,
                "tokenizer_chat_template_sha256": "c" * 64,
                "tokenizer_config_sha256": "d" * 64,
                "tokenizer_assets_sha256": {"tokenizer.json": "1" * 64,
                                            "special_tokens_map.json": "2" * 64},
                "config_sha256": "e" * 64,
                "weights_sha256": {"model.safetensors": "f" * 64},
                "max_seq_length": 4096, "lora_r": 16, "lora_alpha": 32,
                "learning_rate": 0.0002, "seed": 3407, "epochs": 2,
                "instruction_part": "<|im_start|>user\n",
                "response_part": "<|im_start|>assistant\n",
                "target_modules": ["q_proj"], "assistant_eos": "<|im_end|>"},
            "runtime": {"gpu": "A100", "colab_cli_version": "0.7.5"},
            "stop_checks": ["answer", "refusal", "history"],
        }
        spec["dataset"].update(overrides.pop("dataset", {}))
        spec["recipe"].update(overrides.pop("recipe", {}))
        spec.update(overrides)
        spec["source_review"]["binds"] = self.binds(spec)
        if review_override is None:
            self.review = self.write_json("review.json", {
                "status": spec["source_review"]["status"],
                "reviewer": spec["source_review"]["reviewer"],
                "criteria_version": spec["source_review"]["criteria_version"],
                "decisions": {"corpus": "accepted", "split": "accepted",
                              "controls": "accepted"},
                "binds": spec["source_review"]["binds"]})
            spec["source_review"]["path"] = str(self.review)
            spec["source_review"]["sha256"] = PT.sha256_bytes(self.review.read_bytes())
        else:
            spec["source_review"] = review_override
            if not spec["source_review"].get("binds"):
                spec["source_review"]["binds"] = self.binds(spec)
            if spec["source_review"].get("path") and not spec["source_review"].get("sha256"):
                spec["source_review"]["sha256"] = PT.sha256_bytes(
                    Path(spec["source_review"]["path"]).read_bytes())
        return spec

    def write_corpus(self, rows):
        corpus = self.write_jsonl("rows.jsonl", rows)
        self.rows, self.corpus = rows, corpus
        self.ledger, self.audit = self.frozen_split(rows, corpus)
        spec = self.spec()
        spec["dataset"]["refusals"] = sum(1 for r in rows
                                          if r["messages"][-1]["content"] == REFUSAL)
        spec["lineage"] = []
        return spec

    def build(self, spec=None):
        return PT.build_manifest(spec or self.spec(), self.tmp)

    def codes(self, manifest):
        return {failure["code"] for failure in manifest["failures"]}

    # -- the happy path -------------------------------------------------
    def test_valid_fixture_is_ready(self):
        manifest, report = self.build()
        self.assertTrue(report.ok, manifest["failures"])
        self.assertEqual(manifest["status"], "ready-to-launch")
        self.assertEqual(manifest["inputs"]["dataset"]["row_facts"]["rows"], 4)
        self.assertEqual(manifest["inputs"]["dataset"]["row_facts"]["refusals"], 1)

    def test_manifest_is_byte_identical_across_runs(self):
        first, _ = self.build()
        second, _ = self.build()
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class ByteFactsTests(unittest.TestCase):
    def test_crlf_and_lf_are_the_same_rows_and_different_bytes(self):
        lf = b'{"a": 1}\n{"b": 2}\n'
        crlf = lf.replace(b"\n", b"\r\n")
        self.assertEqual(PT.read_jsonl(lf), PT.read_jsonl(crlf))
        self.assertNotEqual(PT.sha256_bytes(lf), PT.sha256_bytes(crlf))
        self.assertEqual(PT.lf_bytes(crlf), lf)

    def test_crlf_digest_reproduces_a_historical_windows_file(self):
        # The adopted corpus was hashed on Windows; the stored copy is LF.
        rows = [{"messages": []}, {"messages": [{"role": "assistant", "content": "x"}]}]
        text = "\r\n".join(json.dumps(r) for r in rows) + "\r\n"
        stored = text.replace("\r\n", "\n").encode("utf-8")
        self.assertEqual(PT.sha256_bytes(PT.crlf_bytes(stored)),
                         PT.sha256_bytes(text.encode("utf-8")))

    def test_row_digest_ignores_key_order_but_not_values(self):
        self.assertEqual(PT.row_digest({"a": 1, "b": 2}), PT.row_digest({"b": 2, "a": 1}))
        self.assertNotEqual(PT.row_digest({"a": 1}), PT.row_digest({"a": 2}))

    def test_corpus_digest_is_order_sensitive(self):
        self.assertNotEqual(PT.corpus_digest([{"a": 1}, {"b": 2}]),
                            PT.corpus_digest([{"b": 2}, {"a": 1}]))


class BlockingTests(Fixture):
    def test_a_draft_spec_never_produces_a_package(self):
        code = PT.main(["--spec", str(self.write_json("draft.json", self.spec(status="draft"))),
                        "--out", str(self.out)])
        self.assertEqual(code, 2)
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "blocked")
        self.assertFalse((self.out / "launch-plan.json").exists())

    def test_dataset_hash_mismatch_blocks(self):
        manifest, _ = self.build(self.spec(dataset={"sha256_bytes": "0" * 64}))
        self.assertIn("dataset_sha256_mismatch", self.codes(manifest))

    def test_declared_rows_and_refusals_are_enforced(self):
        rows = self.build(self.spec(dataset={"rows": 99}))[0]
        self.assertIn("dataset_rows_mismatch", self.codes(rows))
        refusals = self.build(self.spec(dataset={"refusals": 3}))[0]
        self.assertIn("dataset_refusals_mismatch", self.codes(refusals))

    def test_line_ending_claim_must_match_the_file(self):
        crlf = self.write_jsonl("corpus-crlf.jsonl", self.rows, crlf=True)
        spec = self.spec()
        spec["dataset"]["path"] = str(crlf)
        spec["dataset"]["sha256_bytes"] = PT.sha256_bytes(crlf.read_bytes())
        spec["dataset"]["line_ending"] = "lf"
        self.assertIn("dataset_line_ending_mismatch", self.codes(self.build(spec)[0]))

    def test_lineage_subset_is_accepted_and_a_reorder_is_not(self):
        self.assertTrue(self.build()[1].ok)
        shuffled = self.write_jsonl("parent-shuffled.jsonl", [self.rows[2]] + self.rows[:2])
        spec = self.spec()
        spec["lineage"][0]["path"] = str(shuffled)
        spec["lineage"][0]["sha256_bytes"] = PT.sha256_bytes(shuffled.read_bytes())
        self.assertIn("lineage_relation_mismatch", self.codes(self.build(spec)[0]))

    def test_lineage_removed_counts_must_match(self):
        spec = self.spec()
        spec["lineage"][0]["removed_rows"] = {"cited": 7, "refusal": 0}
        self.assertIn("lineage_removed_counts_mismatch", self.codes(self.build(spec)[0]))

    def test_source_review_must_be_accepted_named_and_versioned(self):
        pending = self.write_json("review-pending.json", {
            "status": "needs_review", "reviewer": "r", "criteria_version": "v",
            "decisions": {"corpus": "accepted", "split": "accepted",
                          "controls": "accepted"}, "binds": {}})
        spec = self.spec(source_review={
            "path": str(pending), "sha256": PT.sha256_bytes(pending.read_bytes()),
            "status": "needs_review", "reviewer": "r", "criteria_version": "v",
            "binds": self.binds(self.spec())})
        self.assertIn("source_review_not_accepted", self.codes(self.build(spec)[0]))

    def test_frozen_ledger_must_cover_every_row(self):
        ledger = self.ledger.read_text().splitlines()[:-1]
        self.ledger.write_text("\n".join(ledger) + "\n", encoding="utf-8")
        spec = self.spec(frozen_split={
            "ledger": str(self.ledger), "manifest": str(self.audit),
            "role": "derived_historical_train", "exposure_key": "dev_vs_777"})
        self.assertIn("split_rows_missing", self.codes(self.build(spec)[0]))

    def test_a_family_cannot_straddle_splits(self):
        self.ledger, self.audit = self.frozen_split(overrides={
            0: {"family_id": "shared"}, 1: {"family_id": "shared", "split": "dev"}})
        codes = self.codes(self.build(self.spec())[0])
        self.assertIn("split_family_straddles", codes)

    def test_a_question_only_or_random_policy_is_rejected(self):
        audit = json.loads(self.audit.read_text())
        audit["config"]["random_assignment"] = "seeded shuffle"
        self.write_json("audit-random.json", audit)
        spec = self.spec(frozen_split={**self.spec()["frozen_split"],
                                       "manifest": str(self.tmp / "audit-random.json")})
        self.assertIn("split_random_assignment", self.codes(self.build(spec)[0]))

        audit = json.loads(self.audit.read_text())
        audit["config"]["split_policy"] = "random by question"
        self.write_json("audit-question.json", audit)
        spec = self.spec(frozen_split={**self.spec()["frozen_split"],
                                       "manifest": str(self.tmp / "audit-question.json")})
        codes = self.codes(self.build(spec)[0])
        self.assertTrue({"split_policy_not_component", "split_question_only"} & codes)

    def test_rows_the_audit_marks_not_train_ready_block(self):
        self.ledger, self.audit = self.frozen_split(overrides={
            0: {"train_ready": False, "mechanical": "REVIEW"}})
        spec = self.spec()
        self.assertIn("split_rows_not_train_ready", self.codes(self.build(spec)[0]))

    def test_a_review_split_row_is_not_trainable(self):
        self.ledger, self.audit = self.frozen_split(overrides={1: {"split": "review"}})
        self.assertIn("split_rows_not_train", self.codes(self.build(self.spec())[0]))

    def test_a_wrong_role_blocks(self):
        self.ledger, self.audit = self.frozen_split(overrides={0: {"role": "historical_train"}})
        self.assertIn("split_role_mismatch", self.codes(self.build(self.spec())[0]))

    def test_declared_exposure_must_equal_the_audit(self):
        spec = self.spec(accepted_exposure={"dev_support_exposed": 0,
                                            "dev_context_seen": 0,
                                            "dev_source_unseen": 3})
        self.assertIn("split_exposure_mismatch", self.codes(self.build(spec)[0]))

    def test_a_review_without_byte_bindings_fails(self):
        spec = self.spec()
        spec["source_review"]["binds"] = {}
        self.assertIn("source_review_spec_mismatch", self.codes(self.build(spec)[0]))

    def test_dataset_hash_mismatch_blocks(self):
        manifest, _ = self.build(self.spec(dataset={"sha256_bytes": "0" * 64}))
        self.assertIn("dataset_sha256_mismatch", self.codes(manifest))

    def test_declared_rows_and_refusals_are_enforced(self):
        rows = self.build(self.spec(dataset={"rows": 99}))[0]
        self.assertIn("dataset_rows_mismatch", self.codes(rows))
        refusals = self.build(self.spec(dataset={"refusals": 3}))[0]
        self.assertIn("dataset_refusals_mismatch", self.codes(refusals))

    def test_line_ending_claim_must_match_the_file(self):
        crlf = self.write_jsonl("corpus-crlf.jsonl", self.rows, crlf=True)
        spec = self.spec()
        spec["dataset"]["path"] = str(crlf)
        spec["dataset"]["sha256_bytes"] = PT.sha256_bytes(crlf.read_bytes())
        spec["dataset"]["line_ending"] = "lf"
        self.assertIn("dataset_line_ending_mismatch", self.codes(self.build(spec)[0]))

    def test_lineage_subset_is_accepted_and_a_reorder_is_not(self):
        self.assertTrue(self.build()[1].ok)
        shuffled = self.write_jsonl("parent-shuffled.jsonl", [self.rows[2]] + self.rows[:2])
        spec = self.spec()
        spec["lineage"][0]["path"] = str(shuffled)
        spec["lineage"][0]["sha256_bytes"] = PT.sha256_bytes(shuffled.read_bytes())
        self.assertIn("lineage_relation_mismatch", self.codes(self.build(spec)[0]))

    def test_lineage_removed_counts_must_match(self):
        spec = self.spec()
        spec["lineage"][0]["removed_rows"] = {"cited": 7, "refusal": 0}
        self.assertIn("lineage_removed_counts_mismatch", self.codes(self.build(spec)[0]))

    def test_source_review_must_be_accepted_named_and_versioned(self):
        pending = self.write_json("review-pending.json", {
            "status": "needs_review", "reviewer": "r", "criteria_version": "v",
            "decisions": {"corpus": "accepted", "split": "accepted",
                          "controls": "accepted"}, "binds": {}})
        spec = self.spec(source_review={
            "path": str(pending), "sha256": PT.sha256_bytes(pending.read_bytes()),
            "status": "needs_review", "reviewer": "r", "criteria_version": "v",
            "binds": self.binds(self.spec())})
        self.assertIn("source_review_not_accepted", self.codes(self.build(spec)[0]))

    def test_frozen_ledger_must_cover_every_row(self):
        ledger = self.ledger.read_text().splitlines()[:-1]
        self.ledger.write_text("\n".join(ledger) + "\n", encoding="utf-8")
        spec = self.spec(frozen_split={
            "ledger": str(self.ledger), "manifest": str(self.audit),
            "role": "derived_historical_train", "exposure_key": "dev_vs_777"})
        self.assertIn("split_rows_missing", self.codes(self.build(spec)[0]))

    def test_a_family_cannot_straddle_splits(self):
        self.ledger, self.audit = self.frozen_split(overrides={
            0: {"family_id": "shared"}, 1: {"family_id": "shared", "split": "dev"}})
        codes = self.codes(self.build(self.spec())[0])
        self.assertIn("split_family_straddles", codes)

    def test_a_question_only_or_random_policy_is_rejected(self):
        audit = json.loads(self.audit.read_text())
        audit["config"]["random_assignment"] = "seeded shuffle"
        self.write_json("audit-random.json", audit)
        spec = self.spec(frozen_split={**self.spec()["frozen_split"],
                                       "manifest": str(self.tmp / "audit-random.json")})
        self.assertIn("split_random_assignment", self.codes(self.build(spec)[0]))

        audit = json.loads(self.audit.read_text())
        audit["config"]["split_policy"] = "random by question"
        self.write_json("audit-question.json", audit)
        spec = self.spec(frozen_split={**self.spec()["frozen_split"],
                                       "manifest": str(self.tmp / "audit-question.json")})
        codes = self.codes(self.build(spec)[0])
        self.assertTrue({"split_policy_not_component", "split_question_only"} & codes)

    def test_rows_the_audit_marks_not_train_ready_block(self):
        self.ledger, self.audit = self.frozen_split(overrides={
            0: {"train_ready": False, "mechanical": "REVIEW"}})
        spec = self.spec()
        self.assertIn("split_rows_not_train_ready", self.codes(self.build(spec)[0]))

    def test_a_review_split_row_is_not_trainable(self):
        self.ledger, self.audit = self.frozen_split(overrides={1: {"split": "review"}})
        self.assertIn("split_rows_not_train", self.codes(self.build(self.spec())[0]))

    def test_a_wrong_role_blocks(self):
        self.ledger, self.audit = self.frozen_split(overrides={0: {"role": "historical_train"}})
        self.assertIn("split_role_mismatch", self.codes(self.build(self.spec())[0]))

    def test_declared_exposure_must_equal_the_audit(self):
        spec = self.spec(accepted_exposure={"dev_support_exposed": 0,
                                            "dev_context_seen": 0,
                                            "dev_source_unseen": 3})
        self.assertIn("split_exposure_mismatch", self.codes(self.build(spec)[0]))

    def test_open_control_exact_match_blocks(self):
        control = self.write_jsonl("exact.jsonl", [{"question": TRAIN_Q}])
        spec = self.spec()
        spec["evaluation_controls"][0]["path"] = str(control)
        spec["evaluation_controls"][0]["sha256"] = PT.sha256_bytes(control.read_bytes())
        self.assertIn("eval_leak_exact", self.codes(self.build(spec)[0]))

    def test_near_duplicates_need_both_string_and_content_overlap(self):
        # The repo's rule: similar string and shared content words. A short
        # question such as "what is caching" must still be comparable.
        self.assertTrue(PT.near_duplicate("what is a watermark in a stream processing system",
                                          "what is a watermark in a stream processing pipeline"))
        self.assertFalse(PT.near_duplicate("what is replication", "what is location"))

    def test_open_control_near_duplicate_blocks(self):
        control = self.write_jsonl("near.jsonl", [{"question": CONTROL_NEAR}])
        spec = self.spec()
        spec["evaluation_controls"][0]["path"] = str(control)
        spec["evaluation_controls"][0]["sha256"] = PT.sha256_bytes(control.read_bytes())
        self.assertIn("eval_leak_near", self.codes(self.build(spec)[0]))

    def test_reserved_control_requires_hashes_and_reads_no_text(self):
        reserved = self.write_jsonl("locked.jsonl", [{"question": "hidden"}])
        spec = self.spec()
        spec["evaluation_controls"] = [{
            "name": "locked", "path": str(reserved), "reserved": True,
            "sha256": PT.sha256_bytes(reserved.read_bytes())}]
        spec["evaluation_controls"] = [{
            "name": "locked", "path": str(reserved), "role": "reserved",
            "sha256": PT.sha256_bytes(reserved.read_bytes())}]
        self.assertIn("control_population_mismatch", self.codes(self.build(spec)[0]))

        leaks = self.spec()
        leaks["evaluation_controls"] = [self.locked_control(
            questions_sha256=[PT.question_sha256(TRAIN_Q)])]
        self.assertIn("eval_leak_exact", self.codes(self.build(leaks)[0]))

    def test_declared_collision_must_still_exist(self):
        spec = self.spec()
        spec["expected_seen_collisions"] = [
            {"control": "control", "question_sha256": "f" * 64, "reason": "stale claim"}]
        self.assertIn("declared_collision_stale", self.codes(self.build(spec)[0]))

    def test_a_declared_collision_is_allowed(self):
        control = self.write_jsonl("seen.jsonl", [{"question": TRAIN_Q}])
        spec = self.spec()
        spec["evaluation_controls"][0]["path"] = str(control)
        spec["evaluation_controls"][0]["sha256"] = PT.sha256_bytes(control.read_bytes())
        spec["expected_seen_collisions"] = [
            {"control": "control", "question_sha256": PT.question_sha256(TRAIN_Q),
             "reason": "staged diagnostic item, seen-source by design"}]
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_a_declared_near_duplicate_is_allowed(self):
        control = self.write_jsonl("near-declared.jsonl", [{"question": CONTROL_NEAR}])
        spec = self.spec()
        spec["evaluation_controls"][0]["path"] = str(control)
        spec["evaluation_controls"][0]["sha256"] = PT.sha256_bytes(control.read_bytes())
        spec["expected_seen_near"] = [
            {"control": "control", "question_sha256": PT.question_sha256(CONTROL_NEAR),
             "reason": "same source chunk, different question wording"}]
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_a_stale_near_claim_fails(self):
        spec = self.spec()
        spec["expected_seen_near"] = [
            {"control": "control", "question_sha256": "e" * 64, "reason": "stale"}]
        self.assertIn("declared_near_stale", self.codes(self.build(spec)[0]))

    def test_control_with_no_questions_is_a_schema_drift(self):
        empty = self.write_jsonl("empty.jsonl", [{"id": "x", "prompt": "no question key"}])
        spec = self.spec()
        spec["evaluation_controls"][0]["path"] = str(empty)
        spec["evaluation_controls"][0]["sha256"] = PT.sha256_bytes(empty.read_bytes())
        self.assertIn("control_questions_empty", self.codes(self.build(spec)[0]))


class RowTests(Fixture):
    def test_refusal_with_trailing_text_blocks(self):
        spec = self.write_corpus(self.rows[:3] + [row("explain s3", REFUSAL + " The end.",
                                                     source="gloss")])
        self.assertIn("row_refusal_trailing_text", self.codes(self.build(spec)[0]))

    def test_refusal_with_a_newline_is_not_exact(self):
        spec = self.write_corpus(self.rows[:3] + [row("explain s3", REFUSAL + "\n",
                                                     source="gloss")])
        self.assertIn("row_refusal_not_exact", self.codes(self.build(spec)[0]))

    def test_untagged_label_needs_a_declared_source(self):
        spec = self.write_corpus(self.rows[:3] + [row("explain s3", "A loose gloss.",
                                                     source="unlisted")])
        self.assertIn("row_untagged_label", self.codes(self.build(spec)[0]))

    def test_metadata_copied_into_the_label_blocks(self):
        rows = [dict(r) for r in self.rows]
        rows[0] = json.loads(json.dumps(rows[0]))
        rows[0]["meta"]["turn1_a"] = rows[0]["messages"][-1]["content"]
        spec = self.write_corpus(rows)
        self.assertIn("row_metadata_duplicates_label", self.codes(self.build(spec)[0]))

    def test_engine_prompt_text_in_a_row_blocks(self):
        import prompt
        rows = [json.loads(json.dumps(r)) for r in self.rows]
        rows[0]["messages"][2]["content"] = prompt.SYSTEM[:60] + " [Ch. 1] \"x\""
        spec = self.write_corpus(rows)
        self.assertIn("row_prompt_text", self.codes(self.build(spec)[0]))

    def test_appendix_chapter_labels_count_as_cited(self):
        rows = [row("what is an appendix concept", '[Ch. app01] "It is defined there."')]
        spec = self.write_corpus(rows)
        self.assertNotIn("row_untagged_label", self.codes(self.build(spec)[0]))

    def test_a_repaired_topic_key_is_not_the_prompt(self):
        # meta.question is a topic ("observabilty"); meta.asked is the prompt.
        rows = [row("what is observabilty", '[Ch. 2] "Observability is a practice."',
                    asked="what is observability")]
        spec = self.write_corpus(rows)
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_a_turn_without_a_prompt_marker_blocks(self):
        rows = [row("what is observability", '[Ch. 2] "Observability is a practice."')]
        rows[0]["messages"][1]["content"] = "Passages:\n[Ch. 2] chunk_id=c2\nA passage."
        spec = self.write_corpus(rows)
        self.assertIn("row_prompt_missing", self.codes(self.build(spec)[0]))

    def test_parent_crlf_claim_must_reproduce(self):
        spec = self.spec()
        spec["lineage"][0]["sha256_crlf_historical"] = "0" * 64
        self.assertIn("lineage_crlf_history_mismatch", self.codes(self.build(spec)[0]))

    def test_label_that_repeats_the_question_blocks(self):
        spec = self.write_corpus([row("what is a batch pipeline", "What is a batch pipeline")])
        self.assertIn("row_label_equals_question", self.codes(self.build(spec)[0]))

    def test_duplicate_message_rows_over_budget_block(self):
        rows = [self.rows[0], json.loads(json.dumps(self.rows[0]))] + self.rows[1:]
        spec = self.write_corpus(rows)
        self.assertIn("row_duplicate_full_input", self.codes(self.build(spec)[0]))
        spec["dataset"]["allowed_duplicate_rows"] = 1
        self.assertNotIn("row_duplicate_full_input", self.codes(self.build(spec)[0]))

    def test_missing_question_blocks_grouping(self):
        rows = [row("placeholder", '[Ch. 1] "x"\nGloss.')]
        rows[0]["meta"].pop("question")
        rows[0]["meta"].pop("asked")
        rows[0]["messages"][1]["content"] = "Passages:\n[Ch. 1] chunk_id=c1\nA passage."
        spec = self.write_corpus(rows)
        self.assertIn("row_question_missing", self.codes(self.build(spec)[0]))


class CensusTests(Fixture):
    def test_census_assigns_nothing(self):
        facts = PT.census(self.rows, ["meta.question"], str(self.corpus))
        self.assertIsNone(facts["assignment"])
        self.assertEqual(facts["rows"], len(self.rows))
        self.assertEqual(facts["source_families"], 2)

    def test_census_counts_support_history_and_refusals(self):
        rows = [json.loads(json.dumps(r)) for r in self.rows]
        rows[0]["meta"]["cited"] = ["ch02-002"]
        rows[1]["meta"]["turn1_a"] = "prior answer"
        facts = PT.census(rows, ["meta.question"], str(self.corpus))
        self.assertEqual(facts["rows_with_support_keys"], 1)
        self.assertEqual(facts["rows_with_history"], 1)
        self.assertEqual(facts["refusals"], 1)

    def test_cli_census_prints_no_assignment(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = PT.main(["--census", "--dataset", str(self.corpus)])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIsNone(payload["assignment"])
        self.assertNotIn("row_index", buffer.getvalue())


class RecipeTests(Fixture):
    def test_recipe_must_be_pinned_and_complete(self):
        unpinned, _ = self.build(self.spec(recipe={"base_revision": "main"}))
        self.assertIn("recipe_unpinned", self.codes(unpinned))
        missing, _ = self.build(self.spec(recipe={"epochs": None}))
        self.assertIn("recipe_missing", self.codes(missing))

    def test_template_hash_must_be_a_sha256(self):
        bad, _ = self.build(self.spec(recipe={"tokenizer_chat_template_sha256": "abc"}))
        self.assertIn("recipe_unpinned", self.codes(bad))

    def test_config_and_weight_bytes_must_be_pinned(self):
        missing_config, _ = self.build(self.spec(recipe={"config_sha256": None}))
        self.assertIn("recipe_missing", self.codes(missing_config))
        missing_weights, _ = self.build(self.spec(recipe={"weights_sha256": None}))
        self.assertIn("recipe_missing", self.codes(missing_weights))
        empty_weights, _ = self.build(self.spec(recipe={"weights_sha256": {}}))
        self.assertIn("recipe_missing", self.codes(empty_weights))

    def test_weight_pins_are_sha256s_over_plain_file_names(self):
        bad_hash, _ = self.build(self.spec(
            recipe={"weights_sha256": {"model.safetensors": "not-a-hash"}}))
        self.assertIn("recipe_unpinned", self.codes(bad_hash))
        traversal, _ = self.build(self.spec(
            recipe={"weights_sha256": {"../model.safetensors": "f" * 64}}))
        self.assertIn("recipe_unpinned", self.codes(traversal))
        absolute, _ = self.build(self.spec(
            recipe={"weights_sha256": {"/tmp/model.safetensors": "f" * 64}}))
        self.assertIn("recipe_unpinned", self.codes(absolute))

    def test_structural_index_pin_is_required_when_the_shard_name_is_noncanonical(self):
        blocked, _ = self.build(self.spec(recipe={
            "weights_sha256": {"model.safetensors-00001-of-00001.safetensors": "f" * 64}}))
        self.assertIn("recipe_missing", self.codes(blocked))
        self.assertNotEqual(blocked["status"], "ready-to-launch")

    def test_multi_shard_weights_require_an_index_pin(self):
        blocked, _ = self.build(self.spec(recipe={"weights_sha256": {
            "model-00001-of-00002.safetensors": "f" * 64,
            "model-00002-of-00002.safetensors": "e" * 64}}))
        self.assertIn("recipe_missing", self.codes(blocked))

    def test_index_pin_must_be_a_sha256(self):
        bad, _ = self.build(self.spec(recipe={"weights_index_sha256": "not-a-hash"}))
        self.assertIn("recipe_unpinned", self.codes(bad))

    def test_canonical_single_weight_may_omit_the_index_pin(self):
        good, _ = self.build(self.spec())
        self.assertEqual(good["status"], "ready-to-launch", good.get("failures"))
        self.assertIsNone(good["recipe"].get("weights_index_sha256"))


class CompletionDefectTests(unittest.TestCase):
    def test_clean_completion_has_no_defect(self):
        self.assertEqual(PT.detect_completion_defects(
            '[Ch. 1] "A watermark is a threshold."\nIt marks progress. <|im_end|>'), [])

    def test_empty_and_missing_stop_are_separate(self):
        self.assertIn("empty", PT.detect_completion_defects("   "))
        self.assertIn("missing_stop", PT.detect_completion_defects("a partial answer"))

    def test_cap_hit_is_its_own_code(self):
        self.assertEqual(PT.detect_completion_defects("a partial answer",
                                                      max_new_tokens_hit=True), ["cap_hit"])

    def test_thinking_leak_is_detected_before_the_stop(self):
        text = "<|im_start|>assistant I should think about this <|im_end|>"
        self.assertIn("thinking_leak", PT.detect_completion_defects(text))
        self.assertIn("thinking_leak", PT.detect_completion_defects("thinking hard. <|im_end|>"))

    def test_repetition_loop_is_detected(self):
        loop = " and then the same sentence repeats again. " * 9
        self.assertIn("repetition", PT.detect_completion_defects(loop + "<|im_end|>"))

    def test_refusal_that_keeps_talking_is_a_defect(self):
        self.assertIn("refusal_trailing", PT.detect_completion_defects(
            "Not in this book. But here is a guess. <|im_end|>"))
        self.assertEqual(PT.detect_completion_defects("Not in this book. <|im_end|>"), [])


class RunReportTests(Fixture):
    def report(self):
        manifest, _ = self.build()
        self.recipe = manifest["recipe"]
        self.manifest = manifest
        return {
            "schema": PT.RUN_SCHEMA,
            "dataset": {"sha256_rows": manifest["inputs"]["dataset"]["sha256_rows"],
                        "rows": manifest["inputs"]["dataset"]["row_facts"]["rows"]},
            "recipe": {"base_model": "org/model", "base_revision": "a" * 40,
                       "seed": 3407, "epochs": 2, "lora_r": 16, "lora_alpha": 32},
            "chat_template_sha256": "c" * 64,
            "mode": "train",
            "preflight": {
                "measured_before_train": True, "status": "pass",
                "dataset_sha256": manifest["inputs"]["dataset"]["sha256_bytes"],
                "recipe_sha256": manifest["inputs"]["recipe_sha256"],
                "chat_template_sha256": manifest["recipe"]["tokenizer_chat_template_sha256"],
                "tokenizer_config_sha256": manifest["recipe"]["tokenizer_config_sha256"],
                "tokenizer_assets_sha256": manifest["recipe"]["tokenizer_assets_sha256"],
                "rows_checked": manifest["inputs"]["dataset"]["row_facts"]["rows"],
                "mask_rows_checked": manifest["inputs"]["dataset"]["row_facts"]["rows"],
                "max_tokens": 1000, "truncated_rows": 0},
            "tokens": {"max": 1000, "truncated_rows": 0},
            "masks": {"assistant_label_tokens": 120, "user_system_supervised_tokens": 0,
                      "prior_assistant_supervised_tokens": 0,
                      "target_eos_rows": manifest["inputs"]["dataset"]["row_facts"]["rows"],
                      "family_rows": dict(manifest["rows"]["mask_families"]),
                      "family_eos_rows": dict(manifest["rows"]["mask_families"]),
                      "eos_in_supervised": {"answer": 1, "refusal": 1},
                      "negative_label_supervised_tokens": {"system": 0, "user": 0},
                      "spot_checks": [{"row_index": 0, "supervised_equals_label": True}]},
            "stop_checks": [
                {"kind": "answer", "text": '[Ch. 1] "x"\nGloss. <|im_end|>'},
                {"kind": "refusal", "text": "Not in this book. <|im_end|>"},
                {"kind": "history", "text": '[Ch. 2] "y"\nGloss. <|im_end|>'}],
            "runtime": {"gpu": "A100", "python": "3.12", "torch": "2.9",
                        "transformers": "5.17.0", "trl": "1.0", "unsloth": "2026.10.5"},
            "losses": {"epochs": [{"epoch": 1, "train": 0.8, "eval": 0.7}]},
            "artifacts": {"lora_sha256": "d" * 64, "gguf_sha256": "e" * 64},
        }

    def test_a_complete_report_passes(self):
        report = PT.Report()
        PT.verify_run(self.report(), self.manifest, report)
        self.assertTrue(report.ok, report.failures)

    def test_each_missing_fact_is_named(self):
        cases = {
            "run_dataset_mismatch": lambda r: r["dataset"].update(rows=99),
            "run_recipe_mismatch": lambda r: r["recipe"].update(seed=1),
            "run_template_mismatch": lambda r: r.update(chat_template_sha256="0" * 64),
            "run_truncation": lambda r: r["tokens"].update(max=99999),
            "run_eos_count": lambda r: r["masks"]["eos_in_supervised"].update(answer=2),
            "run_mask_leak": lambda r: r["masks"]["negative_label_supervised_tokens"].update(user=4),
            "run_mask_spot_check": lambda r: r["masks"]["spot_checks"][0].update(
                supervised_equals_label=False),
            "run_stop_check_missing": lambda r: r["stop_checks"].pop(),
            "run_runtime_unrecorded": lambda r: r["runtime"].update(gpu=""),
            "run_losses_missing": lambda r: r.update(losses={"epochs": []}),
            "run_artifact_hash_missing": lambda r: r["artifacts"].update(gguf_sha256="x"),
        }
        for code, mutate in cases.items():
            with self.subTest(code=code):
                payload = self.report()
                mutate(payload)
                report = PT.Report()
                PT.verify_run(payload, self.manifest, report)
                self.assertIn(code, {f["code"] for f in report.failures})

    def test_a_capped_stop_check_fails(self):
        payload = self.report()
        payload["stop_checks"][0].update(max_new_tokens_hit=True)
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_stop_check_cap_hit", {f["code"] for f in report.failures})

    def test_a_blocked_manifest_cannot_be_verified(self):
        report = PT.Report()
        PT.verify_run(self.report(), {"status": "blocked"}, report)
        self.assertIn("manifest_not_ready", {f["code"] for f in report.failures})


class PackageTests(Fixture):
    def test_ready_package_writes_the_measured_colab_commands(self):
        spec = self.write_json("spec.json", self.spec())
        code = PT.main(["--spec", str(spec), "--out", str(self.out)])
        self.assertEqual(code, 0)
        plan = json.loads((self.out / "launch-plan.json").read_text())
        commands = [" ".join(part) for part in plan["commands"]]
        self.assertTrue(any(cmd.startswith("colab new") for cmd in commands))
        self.assertTrue(any("--timeout" in cmd for cmd in commands))
        self.assertTrue(any(cmd.startswith("colab upload") for cmd in commands))
        self.assertTrue(any(cmd.startswith("colab download") for cmd in commands))
        self.assertTrue(any(cmd.startswith("colab stop") for cmd in commands))
        self.assertEqual(plan["cli"]["version"], "0.7.5")

    def test_census_mode_writes_nothing(self):
        code = PT.main(["--census", "--dataset", str(self.corpus)])
        self.assertEqual(code, 0)


class SourceHygieneTests(unittest.TestCase):
    def test_no_network_or_subprocess_imports(self):
        self.assertEqual(PT.hygiene_report()["banned_imports"], [])

    def test_no_checkpoint_or_provider_literals(self):
        self.assertEqual(PT.hygiene_report()["disallowed_literals"], [])

    def test_the_hygiene_scan_would_catch_a_regression(self):
        bad = Path(tempfile.mkdtemp(prefix="hygiene-")) / "bad.py"
        self.addCleanup(shutil.rmtree, bad.parent, True)
        bad.write_text("import requests\nMODEL = 'nekohon_x3'\n", encoding="utf-8")
        report = PT.hygiene_report(bad)
        self.assertEqual(report["banned_imports"], ["requests"])
        self.assertEqual(report["disallowed_literals"], ["nekohon_x3"])

    def test_self_check_exits_zero(self):
        self.assertEqual(PT.main(["--self-check"]), 0)


class ReviewArtifactTests(Fixture):
    """The review file decides; the spec may not claim otherwise."""

    def review_file(self, name, **overrides):
        payload = {"status": "accepted", "reviewer": "reviewer-a",
                   "criteria_version": "source-v1",
                   "decisions": {"corpus": "accepted", "split": "accepted",
                                 "controls": "accepted"},
                   "binds": self.binds(self.spec())}
        payload.update(overrides)
        return self.write_json(name, payload)

    def pointed(self, path):
        spec = self.spec()
        spec["source_review"]["path"] = str(path)
        spec["source_review"]["sha256"] = PT.sha256_bytes(path.read_bytes())
        return spec

    def test_a_rejected_review_file_blocks_even_when_the_spec_says_accepted(self):
        path = self.review_file("review-rejected.json", status="rejected",
                                reviewer="", criteria_version="none",
                                decisions={"corpus": "rejected", "split": "rejected",
                                           "controls": "rejected"})
        spec = self.pointed(path)
        codes = self.codes(self.build(spec)[0])
        self.assertIn("source_review_not_accepted", codes)
        self.assertIn("source_review_decision_rejected", codes)

    def test_a_review_file_without_its_own_binds_blocks(self):
        path = self.review_file("review-nobinds.json")
        payload = json.loads(path.read_text())
        payload.pop("binds")
        self.write_json("review-nobinds.json", payload)
        self.assertIn("source_review_format_unknown",
                      self.codes(self.build(self.pointed(path))[0]))

    def test_the_spec_must_mirror_the_review_file(self):
        path = self.review_file("review-ok.json")
        spec = self.pointed(path)
        spec["source_review"]["reviewer"] = "someone-else"
        self.assertIn("source_review_spec_mismatch", self.codes(self.build(spec)[0]))

    def test_unknown_review_format_blocks(self):
        path = self.write_bytes("review.txt", b"looks fine to me\n")
        self.assertIn("source_review_format_unknown",
                      self.codes(self.build(self.pointed(path))[0]))

    def test_a_review_file_bind_mutation_blocks(self):
        path = self.review_file("review-bind.json")
        payload = json.loads(path.read_text())
        payload["binds"]["dataset_sha256"] = "0" * 64
        self.write_json("review-bind.json", payload)
        self.assertIn("review_not_bound", self.codes(self.build(self.pointed(path))[0]))


class SplitScopeTests(Fixture):
    """Findings and components are read from the ledger, not inferred from the corpus."""

    def test_a_dev_ledger_row_sharing_a_train_component_blocks(self):
        extra = {"id": "dev-row", "source_path": "dev.jsonl", "line": 1,
                 "split": "dev", "family_id": "question:dev", "component_id": "component:0",
                 "role": "dev", "train_ready": False}
        self.ledger.write_text(self.ledger.read_text() + json.dumps(extra) + "\n",
                               encoding="utf-8")
        self.assertIn("split_component_straddles", self.codes(self.build(self.spec())[0]))

    def test_an_undeclared_dev_train_finding_blocks(self):
        audit = json.loads(self.audit.read_text())
        audit["split_findings"] = [{
            "code": "support_cross_split", "key": "fde:ch02-002",
            "splits": ["dev", "train"], "ids": {"dev": ["dev-1"], "train": ["row-0"]}}]
        self.write_json("audit-finding.json", audit)
        spec = self.spec(frozen_split={
            **self.spec()["frozen_split"],
            "manifest": str(self.tmp / "audit-finding.json"),
            "sha256_audit": PT.sha256_bytes((self.tmp / "audit-finding.json").read_bytes())})
        self.assertIn("split_finding_undeclared", self.codes(self.build(spec)[0]))

    def test_a_declared_dev_train_finding_is_allowed(self):
        audit = json.loads(self.audit.read_text())
        audit["split_findings"] = [{
            "code": "support_cross_split", "key": "fde:ch02-002",
            "splits": ["dev", "train"], "ids": {"dev": ["dev-1"], "train": ["row-0"]}}]
        self.write_json("audit-finding-ok.json", audit)
        spec = self.spec(frozen_split={
            **self.spec()["frozen_split"],
            "manifest": str(self.tmp / "audit-finding-ok.json"),
            "sha256_audit": PT.sha256_bytes((self.tmp / "audit-finding-ok.json").read_bytes())})
        spec["accepted_split_findings"] = [{"code": "support_cross_split",
                                            "key": "fde:ch02-002", "reason": "known dev exposure"}]
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_a_review_train_finding_is_a_note_not_a_leak(self):
        audit = json.loads(self.audit.read_text())
        audit["split_findings"] = [{
            "code": "support_cross_split", "key": "fde:ch09-001",
            "splits": ["review", "train"], "ids": {"review": ["pending-1"], "train": ["row-0"]}}]
        self.write_json("audit-review-finding.json", audit)
        spec = self.spec(frozen_split={
            **self.spec()["frozen_split"],
            "manifest": str(self.tmp / "audit-review-finding.json"),
            "sha256_audit": PT.sha256_bytes((self.tmp / "audit-review-finding.json").read_bytes())})
        manifest, report = self.build(spec)
        self.assertNotIn("split_finding_undeclared", self.codes(manifest))
        self.assertIn("split_pending_finding", {n["code"] for n in manifest["notes"]})

    def test_exposure_ids_are_bound(self):
        path = self.review_file = self.write_json("review-ids.json", {
            "status": "accepted", "reviewer": "reviewer-a",
            "criteria_version": "source-v1",
            "decisions": {"corpus": "accepted", "split": "accepted", "controls": "accepted"},
            "binds": {**self.binds(self.spec()), "exposure_ids_sha256": "0" * 64}})
        spec = self.spec()
        spec["source_review"]["path"] = str(path)
        spec["source_review"]["sha256"] = PT.sha256_bytes(path.read_bytes())
        self.assertIn("review_not_bound", self.codes(self.build(spec)[0]))


class ProtectedSurfaceTests(Fixture):
    """A required protected surface must be present, populated, and attested."""

    def test_zero_controls_blocks(self):
        spec = self.spec(evaluation_controls=[])
        self.assertIn("required_control_missing", self.codes(self.build(spec)[0]))

    def test_a_dummy_hash_under_the_declared_population_blocks(self):
        spec = self.spec(evaluation_controls=[
            self.locked_control(questions_sha256=["0" * 64]),
            self.spec()["evaluation_controls"][0]])
        codes = self.codes(self.build(spec)[0])
        self.assertTrue({"control_population_mismatch", "control_hash_list_unattested"} & codes)

    def test_an_unattested_hash_list_blocks(self):
        entry = self.locked_control(attestation={"reviewer": "", "complete": False,
                                                 "method": ""})
        spec = self.spec(evaluation_controls=[entry,
                                              self.spec()["evaluation_controls"][0]])
        self.assertIn("control_attestation_missing", self.codes(self.build(spec)[0]))

    def test_a_complete_attested_list_passes(self):
        self.assertTrue(self.build()[1].ok, self.build()[0]["failures"])

    def test_a_legacy_development_gate_needs_no_hash_list(self):
        spec = self.spec()
        legacy = [c for c in spec["evaluation_controls"] if c["name"] == "legacy"][0]
        self.assertNotIn("questions_sha256", legacy)
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])


class MaskProofTests(RunReportTests):
    def test_empty_masks_block(self):
        payload = self.report()
        payload["masks"] = {}
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_masks_unmeasured", {f["code"] for f in report.failures})

    def test_missing_assistant_label_coverage_blocks(self):
        payload = self.report()
        payload["masks"].pop("assistant_label_tokens")
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_label_coverage_missing", {f["code"] for f in report.failures})

    def test_supervised_prompt_tokens_block(self):
        payload = self.report()
        payload["masks"]["user_system_supervised_tokens"] = 12
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_mask_leak", {f["code"] for f in report.failures})

    def test_missing_preflight_section_blocks(self):
        payload = self.report()
        payload.pop("preflight")
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_preflight_missing", {f["code"] for f in report.failures})

    def test_preflight_only_is_blocked_train_not_a_pass(self):
        payload = self.report()
        payload["mode"] = "preflight-only"
        report = PT.Report()
        details = PT.verify_run(payload, self.manifest, report)
        self.assertEqual(details.get("status"), "preflight-only")
        self.assertIn("run_train_not_proven", {f["code"] for f in report.failures})


class RunnerBindingTests(Fixture):
    def test_swapped_runner_bytes_block(self):
        spec = self.spec()
        self.runner.write_bytes(b"# tampered after review\n")
        self.assertIn("runner_sha256_mismatch", self.codes(self.build(spec)[0]))

    def test_runner_and_deps_are_bound_in_the_manifest(self):
        manifest, _ = self.build()
        runner = manifest["inputs"]["runner"]
        self.assertEqual(runner["sha256"], PT.sha256_bytes(self.runner.read_bytes()))
        self.assertEqual(runner["deps_sha256"], PT.sha256_bytes(self.deps.read_bytes()))

    def test_launch_plan_is_not_runnable_without_a_consuming_runner(self):
        spec = self.spec()
        spec["runner"]["consumes_frozen_inputs"] = False
        spec["runner"]["preflight_gate"] = False
        spec["source_review"]["binds"] = self.binds(spec)
        manifest, _ = self.build(spec)
        self.assertEqual(manifest["status"], "blocked_runner")
        plan = PT.launch_plan(manifest, spec)
        self.assertFalse(plan["runnable"])
        self.assertIn("consume", plan["blocked_reason"])


class RequiredControlRoleTests(Fixture):
    def test_a_required_name_supplied_as_open_blocks(self):
        spec = self.spec(evaluation_controls=[
            {"name": "locked", "path": str(self.control), "role": "open",
             "sha256": PT.sha256_bytes(self.control.read_bytes())}])
        self.assertIn("required_control_not_protected", self.codes(self.build(spec)[0]))

    def test_a_required_name_supplied_as_development_blocks(self):
        spec = self.spec(evaluation_controls=[
            {"name": "locked", "path": str(self.legacy), "role": "development",
             "sha256": PT.sha256_bytes(self.legacy.read_bytes())}])
        self.assertIn("required_control_not_protected", self.codes(self.build(spec)[0]))

    def test_a_legacy_public_control_outside_the_required_list_stays_legit(self):
        self.assertTrue(self.build()[1].ok, self.build()[0]["failures"])


class FamilyMaskTests(RunReportTests):
    def test_masks_must_cover_every_data_family(self):
        payload = self.report()
        payload["masks"]["family_rows"].pop("refusal")
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_family_missing", {f["code"] for f in report.failures})

    def test_family_counts_must_match_the_dataset(self):
        payload = self.report()
        payload["masks"]["family_rows"]["answer"] = 99
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_family_count_mismatch", {f["code"] for f in report.failures})

    def test_every_target_row_must_show_its_eos(self):
        payload = self.report()
        payload["masks"]["family_eos_rows"]["refusal"] = 0
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_eos_count", {f["code"] for f in report.failures})

    def test_prior_assistant_turns_cannot_be_supervised(self):
        payload = self.report()
        payload["masks"]["prior_assistant_supervised_tokens"] = 3
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_prior_history_supervised", {f["code"] for f in report.failures})


class InventoryTests(Fixture):
    def test_an_empty_required_list_cannot_opt_out(self):
        spec = self.spec(required_controls=[], evaluation_controls=[
            self.spec()["evaluation_controls"][0]])
        self.assertIn("required_inventory_empty", self.codes(self.build(spec)[0]))

    def test_an_attested_empty_inventory_is_explicit(self):
        spec = self.spec(required_controls=[], evaluation_controls=[
            self.spec()["evaluation_controls"][0]],
            protected_inventory={"status": "none-attested", "reviewer": "reviewer-a",
                                 "no_heldout_claim": True})
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_inventory_names_must_match_the_required_list(self):
        spec = self.spec(protected_inventory={"names": ["locked", "fair-locked"],
                                              "reviewer": "reviewer-a"})
        self.assertIn("protected_inventory_incomplete", self.codes(self.build(spec)[0]))


class PreflightProofTests(RunReportTests):
    def test_preflight_must_carry_dataset_and_recipe_hashes(self):
        payload = self.report()
        payload["preflight"].pop("dataset_sha256")
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_preflight_incomplete", {f["code"] for f in report.failures})

    def test_preflight_must_carry_measured_counts(self):
        payload = self.report()
        payload["preflight"].pop("rows_checked")
        payload["preflight"].pop("mask_rows_checked")
        payload["preflight"].pop("max_tokens")
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_preflight_incomplete", {f["code"] for f in report.failures})


class TokenizerPinTests(RunReportTests):
    def test_runtime_tokenizer_config_must_match_the_approved_hash(self):
        payload = self.report()
        payload["preflight"]["tokenizer_config_sha256"] = "e" * 64
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_tokenizer_config_mismatch",
                      {f["code"] for f in report.failures})

    def test_runtime_tokenizer_assets_must_match_the_approved_map(self):
        payload = self.report()
        payload["preflight"]["tokenizer_assets_sha256"] = {
            "tokenizer.json": "9" * 64,
            "special_tokens_map.json": payload["preflight"]
                                        ["tokenizer_assets_sha256"]["special_tokens_map.json"]}
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertIn("run_tokenizer_asset_mismatch",
                      {f["code"] for f in report.failures})

    def test_an_unpinned_tokenizer_asset_map_cannot_be_approved(self):
        spec = self.spec(recipe={"tokenizer_assets_sha256": None})
        self.assertIn("recipe_missing", self.codes(self.build(spec)[0]))

    def test_tokenizer_asset_map_requires_a_representation(self):
        spec = self.spec(recipe={"tokenizer_assets_sha256": {
            "special_tokens_map.json": "1" * 64}})
        self.assertIn("tokenizer_assets_representation_missing",
                      self.codes(self.build(spec)[0]))

    def test_vocab_and_merges_are_an_accepted_representation(self):
        spec = self.spec(recipe={"tokenizer_assets_sha256": {
            "vocab.json": "1" * 64, "merges.txt": "2" * 64}})
        manifest, report = self.build(spec)
        self.assertTrue(report.ok, manifest.get("failures"))

    def test_an_unpinned_tokenizer_config_cannot_be_approved(self):
        spec = self.spec(recipe={"tokenizer_config_sha256": None})
        self.assertIn("recipe_missing", self.codes(self.build(spec)[0]))

    def test_flipping_the_approved_hash_breaks_the_review_binding(self):
        spec = self.spec()
        spec["recipe"]["tokenizer_config_sha256"] = "f" * 64
        self.assertIn("review_not_bound", self.codes(self.build(spec)[0]))

    def test_expected_and_runtime_matching_is_the_positive_control(self):
        self.assertTrue(self.build()[1].ok, self.build()[0]["failures"])
        payload = self.report()
        report = PT.Report()
        PT.verify_run(payload, self.manifest, report)
        self.assertTrue(report.ok, report.failures)


class MessageQuestionTests(Fixture):
    """The user turn is the question when metadata carries none."""

    def messages_only(self, question, label='[Ch. 1] "A watermark is a threshold."\nIt marks progress.'):
        return {
            "messages": [
                {"role": "system", "content": "You answer only from the passages below."},
                {"role": "user", "content": "Question: %s\n\nPassages:\n[Ch. 1] chunk_id=c1\nA passage." % question},
                {"role": "assistant", "content": label},
            ],
            "meta": {"source": "synthetic-additions", "id": "meta-id-unrelated"},
        }

    def test_question_of_reads_the_user_turn_and_never_an_id(self):
        row = self.messages_only("what is a watermark")
        self.assertEqual(PT.question_of(row, ["meta.question", "meta.asked"]),
                         "what is a watermark")
        self.assertNotEqual(PT.question_of(row, ["meta.question", "meta.asked"]),
                            "meta-id-unrelated")

    def test_a_messages_only_row_cannot_hide_a_protected_question(self):
        self.locked_hashes = [PT.question_sha256("reserved-question-1"),
                              PT.sha256_bytes(b"unused")]
        spec = self.write_corpus([self.messages_only("reserved-question-1")])
        self.assertIn("eval_leak_exact", self.codes(self.build(spec)[0]))

    def test_a_different_question_in_the_user_turn_passes(self):
        self.locked_hashes = [PT.question_sha256("reserved-question-1"),
                              PT.sha256_bytes(b"unused")]
        spec = self.write_corpus([self.messages_only("what is a batch pipeline")])
        self.assertTrue(self.build(spec)[1].ok, self.build(spec)[0]["failures"])

    def test_an_earlier_user_turn_cannot_hide_a_protected_question(self):
        self.locked_hashes = [PT.question_sha256("reserved-question-1"),
                              PT.sha256_bytes(b"unused")]
        row = self.messages_only("what is a batch pipeline")
        row["messages"] = [
            row["messages"][0],
            {"role": "user", "content": "Question: reserved-question-1\n\nPassages:\n[Ch. 1] chunk_id=c1\nA passage."},
            {"role": "assistant", "content": '[Ch. 1] "A watermark is a threshold."'},
            {"role": "user", "content": "Question: what is a batch pipeline\n\nPassages:\n[Ch. 1] chunk_id=c1\nA passage."},
            {"role": "assistant", "content": '[Ch. 2] "Batch processing handles bounded data."'},
        ]
        spec = self.write_corpus([row])
        self.assertIn("eval_leak_exact", self.codes(self.build(spec)[0]))


if __name__ == "__main__":
    unittest.main()
