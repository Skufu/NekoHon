"""The reviewed runner must refuse, not warn.

Every test builds one complete package with the real `prepare_training` gate,
then breaks exactly one thing. The fake tokenizer is a boundary double: it
proves the mask arithmetic and the refusal paths, never that a GPU run is
correct. No test imports torch, downloads a model, or touches `data/`.
"""

import contextlib
import builtins
import io
import json
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "colab"))

import prepare_training as PT  # noqa: E402
import training_reviewed as TR  # noqa: E402

PAD = "<|vision_pad|>"
EOS = "<|im_end|>"
REFUSAL = "Not in this book."
FAKE_TEMPLATE = "fake qwen3.5 chat template used only to pin a hash"
REAL_TOKENIZER_CONFIG_SHA = (
    "50470511708577d43f7c18c2d8e2ab02fb8abf3add1c40f60b74579d6d16e27e")


def train_row(question, label, source="synthetic", history=False):
    user = "Question: %s?\n\nPassages:\n[Ch. 1] chunk_id=c1\nA passage." % question
    messages = [{"role": "system", "content": "You answer only from the passages below."},
                {"role": "user", "content": user}]
    if history:
        messages += [
            {"role": "assistant", "content": "A first-turn answer about the passage."},
            {"role": "user", "content": "Question: and what follows from that?\n\nPassages: same"},
        ]
    messages.append({"role": "assistant", "content": label})
    return {"messages": messages,
            "meta": {"question": question, "asked": question, "source": source,
                     "split": "train"}}


def validation_row(ledger_id, question):
    user = "Question: %s?\n\nPassages:\n[Ch. 2] chunk_id=c2\nAnother passage." % question
    return {"messages": [{"role": "system", "content": "You answer only from the passages below."},
                         {"role": "user", "content": user},
                         {"role": "assistant", "content": '[Ch. 2] "A dev answer."\nIt is a gloss.'}],
            "meta": {"ledger_id": ledger_id, "question": question, "split": "train"}}


class FakeTokenizer:
    """Deterministic render + char tokenizer. Boundary double only."""

    specials = {"<|im_start|>": 1, "<|im_end|>": 100, PAD: 7}

    def __init__(self, template=FAKE_TEMPLATE, eos=EOS, pad=PAD, pad_id=7,
                 merges=(), scaffold=None, thinking=True, reject_thinking_kwarg=False):
        self.chat_template = template
        self.eos_token = eos
        self.eos_token_id = 100
        self.pad_token = pad
        self.pad_token_id = pad_id
        self.name_or_path = "org/model"
        self.merges = set(merges)
        self.scaffold = scaffold
        self.thinking = thinking
        self.reject_thinking_kwarg = reject_thinking_kwarg
        self.pieces = dict(self.specials)
        self.ids = {value: key for key, value in self.pieces.items()}
        self.next_id = 200

    def _piece_id(self, piece):
        if piece not in self.pieces:
            self.pieces[piece] = self.next_id
            self.ids[self.next_id] = piece
            self.next_id += 1
        return self.pieces[piece]

    def _merge(self, pieces):
        changed = True
        while changed:
            changed = False
            for index in range(len(pieces) - 1):
                if (pieces[index], pieces[index + 1]) in self.merges:
                    pieces = pieces[:index] + [pieces[index] + pieces[index + 1]] + pieces[index + 2:]
                    changed = True
                    break
        return pieces

    def encode(self, text):
        pieces, position = [], 0
        for match in re.finditer(r"<\|[^|]*\|>|<think>|</think>", text):
            pieces.extend(list(text[position:match.start()]))
            pieces.append(match.group(0))
            position = match.end()
        pieces.extend(list(text[position:]))
        return [self._piece_id(piece) for piece in self._merge(pieces)]

    def __call__(self, text, add_special_tokens=False, return_tensors=None):
        return {"input_ids": self.encode(text)}

    def decode(self, ids, skip_special_tokens=False, clean_up_tokenization_spaces=False):
        return "".join(self.ids.get(int(token), "\uFFFD") for token in ids)

    def _render(self, messages, add_generation_prompt, thinking):
        out = []
        for index, message in enumerate(messages):
            out.append("<|im_start|>%s\n" % message["role"])
            if message["role"] == "assistant" and index == len(messages) - 1 \
                    and not add_generation_prompt:
                scaffold = "<think>\n\n</think>\n\n"
                if self.scaffold is not None:
                    scaffold = self.scaffold(message["content"])
                out.append(scaffold)
            out.append(str(message["content"]))
            out.append("<|im_end|>\n")
        if add_generation_prompt:
            out.append("<|im_start|>assistant\n")
            if self.reject_thinking_kwarg:
                raise TypeError("unexpected keyword argument 'enable_thinking'")
            if thinking is True and self.thinking:
                out.append("<think>\n")
            else:
                out.append("<think>\n\n</think>\n\n")
        return "".join(out)

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False,
                            enable_thinking=None, **kwargs):
        if tokenize:
            raise ValueError("the runner renders text only")
        return self._render(messages, add_generation_prompt, enable_thinking)


class NoEosTokenizer(FakeTokenizer):
    def _render(self, messages, add_generation_prompt, thinking):
        text = super()._render(messages, add_generation_prompt, thinking)
        if add_generation_prompt or not messages or messages[-1].get("role") != "assistant":
            return text
        return text[:-len("<|im_end|>\n")]


class DoubleEosTokenizer(FakeTokenizer):
    def _render(self, messages, add_generation_prompt, thinking):
        text = super()._render(messages, add_generation_prompt, thinking)
        if add_generation_prompt or not messages or messages[-1].get("role") != "assistant":
            return text
        return text[:-len("<|im_end|>\n")] + "<|im_end|><|im_end|>\n"


class IgnoringThinkingTokenizer(FakeTokenizer):
    def _render(self, messages, add_generation_prompt, thinking):
        return super()._render(messages, add_generation_prompt, False)


class DeadTokenizer(FakeTokenizer):
    """The transformers 5.17.0 failure shape: loads, encodes nothing."""

    def __call__(self, text, add_special_tokens=False, return_tensors=None):
        return {"input_ids": self.encode(text)}

    def encode(self, text):
        return []

    def decode(self, ids, skip_special_tokens=False, clean_up_tokenization_spaces=False):
        return ""


def recipe(**overrides):
    value = {
        "base_model": "org/model", "base_revision": "a" * 40,
        "tokenizer_revision": "a" * 40,
        "tokenizer_chat_template_sha256": TR.sha256_text(FAKE_TEMPLATE),
        "tokenizer_config_sha256": "d" * 64,
        "tokenizer_assets_sha256": {"tokenizer.json": "1" * 64,
                                   "special_tokens_map.json": "2" * 64},
        "config_sha256": "e" * 64,
        "weights_sha256": {"model.safetensors": "f" * 64},
        "weights_index_sha256": None,
        "max_seq_length": 4096, "lora_r": 16, "lora_alpha": 32,
        "learning_rate": 0.0002, "seed": 3407, "epochs": 2,
        "lora_dropout": 0.0,
        "instruction_part": "<|im_start|>user\n",
        "response_part": "<|im_start|>assistant\n",
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                           "gate_proj", "up_proj", "down_proj"],
        "assistant_eos": EOS,
    }
    value.update(overrides)
    return value


class Fixture(unittest.TestCase):
    """One complete package, built by the real gate, then mutated per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reviewed-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.build()

    def write_json(self, name, obj):
        path = self.tmp / name
        path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def write_jsonl(self, name, rows):
        path = self.tmp / name
        path.write_bytes(("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
                          + "\n").encode("utf-8"))
        return path

    def build(self, dev_rows=2, validation_take=2, runner_path=None,
              recipe_overrides=None, derived=False):
        self.rows = [
            train_row("what is a watermark in a stream processing system",
                      '[Ch. 1] "A watermark is a threshold."\nIt marks progress.'),
            train_row("what is a figure id in a caption", REFUSAL),
            train_row("what changed after the first turn", '[Ch. 3] "A later answer."\nIt follows.',
                      history=True),
            train_row("explain s3", "Amazon S3 is durable object storage.", source="gloss"),
        ]
        self.validation_rows = [validation_row("dev-row-%d" % number, "dev question %d" % number)
                                for number in range(1, validation_take + 1)]
        if derived:
            for number, row in enumerate(self.rows, 1):
                row["meta"]["ledger_id"] = "train-row-%d" % number
        self.corpus = self.write_jsonl("corpus.jsonl", self.rows)
        self.validation = self.write_jsonl("validation.jsonl", self.validation_rows)
        self.recipe = recipe(**(recipe_overrides or {}))
        self.runner = Path(runner_path) if runner_path else ROOT / "artifacts/colab/training_reviewed.py"
        self.deps = self.tmp / "deps.py"
        self.deps.write_bytes(b"# synthetic deps\n")
        self.ledger_entries = []
        for index, row in enumerate(self.rows, 1):
            self.ledger_entries.append({
                "id": "train-row-%d" % index, "source_path": str(self.corpus),
                "line": index, "split": "train", "family_id": "family:t%d" % index,
                "component_id": "component:t%d" % index,
                "role": "derived_historical_train", "train_ready": True,
                "messages_sha256": TR.row_messages_sha256(row)})
        for number in range(1, dev_rows + 1):
            dev_row = (self.validation_rows[number - 1]
                       if number <= len(self.validation_rows) else None)
            self.ledger_entries.append({
                "id": "dev-row-%d" % number, "source_path": str(self.validation),
                "line": number, "split": "dev", "family_id": "family:dev",
                "component_id": "component:dev", "role": "dev", "train_ready": False,
                "messages_sha256": TR.row_messages_sha256(dev_row) if dev_row else None,
                "user_prompt_sha256": TR.sha256_text(
                    next(m["content"] for m in dev_row["messages"]
                         if m["role"] == "user")) if dev_row else None,
                "target_sha256": TR.sha256_text(
                    dev_row["messages"][-1]["content"]) if dev_row else None})
        self.ledger = self.write_jsonl("ledger.jsonl", self.ledger_entries)
        self.audit = self.write_json("audit-manifest.json", {
            "audit": "training_audit", "semantic_certification": "NOT CLAIMED",
            "config": {"random_assignment": "none", "seed": 20261029,
                       "split_policy": "connected components over exact question, family, "
                                       "source, history referent; whole components only"},
            "split_findings": [],
            "exposure": {"dev_vs_777": {
                "dev_support_exposed": 0, "dev_context_seen": 0, "dev_source_unseen": 2,
                "support_exposed_ids": [], "context_seen_ids": [], "exact_question_ids": []}}})
        self.control = self.write_jsonl("control.jsonl", [{"id": "c1", "question": "unrelated"}])
        self.locked = self.write_jsonl("locked.jsonl", [{"opaque": True}])
        self.legacy = self.write_jsonl("legacy.jsonl", [{"id": "l1", "question": "legacy"}])
        self.manifest_path = self.tmp / "manifest.json"
        self.contract_path = self.tmp / "contract.json"
        self.spec = self.build_spec()
        manifest, report = PT.build_manifest(self.spec, self.tmp)
        self.assertTrue(report.ok, manifest.get("failures"))
        self.assertEqual(manifest["status"], "ready-to-launch")
        self.manifest = manifest
        self.manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
        self.contract = self.build_contract()
        self.write_contract()

    def build_spec(self):
        review = {
            "status": "accepted", "reviewer": "reviewer-a",
            "criteria_version": "reassessment-2026-10-30",
            "decisions": {"corpus": "accepted", "split": "accepted", "controls": "accepted"},
            "binds": {}}
        spec = {
            "schema": PT.SCHEMA, "status": "certified", "release_id": "test-release",
            "dataset": {
                "path": str(self.corpus),
                "sha256_bytes": PT.sha256_bytes(self.corpus.read_bytes()),
                "sha256_rows": PT.corpus_digest(self.rows),
                "rows": len(self.rows), "refusals": 1, "line_ending": "lf",
                "question_paths": ["meta.question", "meta.asked"],
                "label_path": "messages[-1].content",
                "allow_untagged_sources": ["gloss"], "allowed_duplicate_rows": 0},
            "lineage": [],
            "source_review": {"path": str(self.tmp / "review.json"), "sha256": "",
                               "status": "accepted", "reviewer": "reviewer-a",
                               "criteria_version": "reassessment-2026-10-30",
                               "binds": {}},
            "frozen_split": {
                "ledger": str(self.ledger), "manifest": str(self.audit),
                "sha256_ledger": PT.sha256_bytes(self.ledger.read_bytes()),
                "sha256_audit": PT.sha256_bytes(self.audit.read_bytes()),
                "role": "derived_historical_train", "exposure_key": "dev_vs_777"},
            "accepted_exposure": {"dev_support_exposed": 0, "dev_context_seen": 0,
                                  "dev_source_unseen": 2},
            "accepted_split_findings": [],
            "required_controls": ["locked"],
            "evaluation_controls": [
                {"name": "control", "path": str(self.control), "reserved": False,
                 "sha256": PT.sha256_bytes(self.control.read_bytes())},
                {"name": "locked", "path": str(self.locked), "role": "reserved",
                 "sha256": PT.sha256_bytes(self.locked.read_bytes()),
                 "questions_count": 1,
                 "questions_sha256": [PT.sha256_bytes(b"reserved")],
                 "list_sha256": PT.sha256_bytes(PT.sha256_bytes(b"reserved").encode()),
                 "attestation": {"reviewer": "reviewer-a", "complete": True,
                                 "method": "hashes extracted read-only"}},
                {"name": "legacy", "path": str(self.legacy), "role": "development",
                 "sha256": PT.sha256_bytes(self.legacy.read_bytes())}],
            "expected_seen_collisions": [],
            "runner": {"path": str(self.runner), "deps": str(self.deps),
                       "sha256": PT.sha256_bytes(self.runner.read_bytes()),
                       "deps_sha256": PT.sha256_bytes(self.deps.read_bytes()),
                       "consumes_frozen_inputs": True, "preflight_gate": True},
            "recipe": dict(self.recipe),
            "runtime": {"gpu": "A100", "colab_cli_version": "0.7.5"},
            "stop_checks": ["answer", "refusal", "history"],
        }
        spec["source_review"]["binds"] = self.binds(spec)
        review.update({"binds": spec["source_review"]["binds"]})
        review_path = self.write_json("review.json", review)
        spec["source_review"]["path"] = str(review_path)
        spec["source_review"]["sha256"] = PT.sha256_bytes(review_path.read_bytes())
        return spec

    def binds(self, spec):
        split = PT.verify_frozen_split(self.rows, spec, PT.Report())
        return {
            "dataset_sha256": PT.sha256_bytes(self.corpus.read_bytes()),
            "rows": len(self.rows),
            "recipe_sha256": PT.sha256_bytes(PT.canonical_json(spec["recipe"]).encode()),
            "ledger_sha256": split["sha256_ledger"],
            "audit_manifest_sha256": split["sha256_audit"],
            "exposure": split["exposure"],
            "exposure_ids_sha256": PT.sha256_bytes(b""),
            "tokenizer_config_sha256": spec["recipe"]["tokenizer_config_sha256"],
            "runner_sha256": PT.sha256_bytes(self.runner.read_bytes()),
            "deps_sha256": PT.sha256_bytes(self.deps.read_bytes()),
        }

    def write_fixture_inventory(self):
        protected_hash = PT.question_sha256("protected synthetic question")
        self.inventory = self.write_json("inventory.json", {
            "controls": [{
                "name": "locked", "role": "reserved",
                "path": str(self.locked), "sha256": PT.sha256_bytes(self.locked.read_bytes()),
                "bytes": len(self.locked.read_bytes()),
                "union": {"hashes": [protected_hash], "unique": 1,
                          "list_sha256": TR.sha256_text(protected_hash)},
                "entry": {"attestation": {"reviewer": "reviewer-a"}},
                "rows_selected": 1, "rows_total": 1}],
            "status": "fixture"})
        self.fragment = self.write_json("spec-fragment.json",
                                        {"required_controls": ["locked"]})
        inventory_sha = PT.sha256_bytes(self.inventory.read_bytes())
        fragment_sha = PT.sha256_bytes(self.fragment.read_bytes())
        self.receipt = self.write_json("receipt.json", {
            "schema": "fixture-receipt/1", "verdict": "REVIEW_ACCEPTED",
            "binding": {
                "opaque_inventory": {"inventory_sha256": inventory_sha,
                                     "spec_fragment_sha256": fragment_sha,
                                     "hashes": 1},
                "train_sha256": PT.sha256_bytes(self.corpus.read_bytes()),
                "validation_sha256": PT.sha256_bytes(self.validation.read_bytes()),
                "train_rows": len(self.rows), "validation_rows": len(self.validation_rows),
                "counts": {"train": len(self.rows),
                           "validation": len(self.validation_rows)}}})
        return {"path": str(self.inventory), "sha256": inventory_sha,
                "fragment_path": str(self.fragment), "fragment_sha256": fragment_sha,
                "required_controls": ["locked"],
                "receipt": {"path": str(self.receipt),
                            "sha256": PT.sha256_bytes(self.receipt.read_bytes())}}

    def build_contract(self):
        ids = [row["meta"]["ledger_id"] for row in self.validation_rows]
    def build_contract(self):
        ids = [row["meta"]["ledger_id"] for row in self.validation_rows]
        by_id = {entry["id"]: entry for entry in self.ledger_entries}
        families = {by_id[item]["family_id"] for item in ids}
        components = {by_id[item]["component_id"] for item in ids}
        return {
            "schema": TR.CONTRACT_SCHEMA, "release_id": "test-release",
            "manifest_sha256": PT.sha256_bytes(self.manifest_path.read_bytes()),
            "model": {"pad_token": PAD, "thinking_scaffold": True},
            "deps_sha256": PT.sha256_bytes(self.deps.read_bytes()),
            "protected_inventory": self.write_fixture_inventory(),
            "validation": {
                "path": str(self.validation),
                "sha256_bytes": PT.sha256_bytes(self.validation.read_bytes()),
                "rows": len(self.validation_rows), "role": "dev-internal",
                "row_id_path": "meta.ledger_id",
                "ledger_ids_sha256": TR.sorted_hash(ids),
                "family_ids_sha256": TR.sorted_hash(families),
                "component_ids_sha256": TR.sorted_hash(components),
                "split_manifest_sha256": PT.sha256_bytes(self.audit.read_bytes())},
            "export": {"gguf": "q4_k_m", "merged_16bit": True},
        }

    def write_contract(self):
        self.contract["manifest_sha256"] = PT.sha256_bytes(self.manifest_path.read_bytes())
        self.contract_path.write_text(
            json.dumps(self.contract, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def rewrite_manifest(self, manifest):
        self.manifest = manifest
        self.manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
        self.write_contract()

    def mutate_ledger(self, mutate):
        entries = [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]
        mutate(entries)
        self.ledger.write_bytes(("\n".join(json.dumps(entry) for entry in entries) + "\n").encode())
        manifest = json.loads(json.dumps(self.manifest))
        manifest["inputs"]["split"]["sha256_ledger"] = PT.sha256_bytes(self.ledger.read_bytes())
        self.rewrite_manifest(manifest)

    def mutate_contract(self, mutate):
        mutate(self.contract)
        self.write_contract()

    def package(self):
        return TR.load_package(str(self.manifest_path), str(self.contract_path))

    def codes(self, package):
        return {failure["code"] for failure in package.issues.failures}

    def measure(self, tokenizer=None, recipe_value=None, rows=None, require=None):
        issues = TR.new_issues()
        measured = TR.measure_rows(rows or self.rows, tokenizer or FakeTokenizer(),
                                   recipe_value or self.recipe, issues, "train",
                                   require_families=require)
        return measured, issues


class PackageTests(Fixture):
    def test_good_package_passes(self):
        package = self.package()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertEqual(package.facts["dataset"]["rows"], 4)
        self.assertEqual(package.facts["validation"]["rows"], 2)

    def test_fake_control_summary_is_refused(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["inputs"]["evaluation_controls"] = [{
            "name": "reserved-fake", "role": "reserved",
            "checked_hashes": 1, "attested_by": "nobody"}]
        self.rewrite_manifest(manifest)
        codes = self.codes(self.package())
        self.assertIn("protected_control_unknown", codes)

    def test_inventory_hash_is_bound(self):
        self.mutate_contract(lambda contract: contract["protected_inventory"].update(
            {"sha256": "0" * 64}))
        self.assertIn("protected_inventory_hash_mismatch", self.codes(self.package()))

    def test_control_population_is_bound_to_the_inventory(self):
        manifest = json.loads(json.dumps(self.manifest))
        for entry in manifest["inputs"]["evaluation_controls"]:
            if entry.get("name") == "locked":
                entry["checked_hashes"] = 2
        self.rewrite_manifest(manifest)
        self.assertIn("protected_control_population_mismatch",
                      self.codes(self.package()))

    def test_tokenizer_revision_pin_is_unsupported(self):
        self.build(recipe_overrides={"tokenizer_revision": "b" * 40})
        self.assertIn("tokenizer_revision_unsupported", self.codes(self.package()))

    def test_validation_row_hash_is_enforced(self):
        rows = json.loads(json.dumps(self.validation_rows))
        rows[0]["messages"][-1]["content"] = '[Ch. 2] "A changed dev answer."\nIt differs.'
        self.validation.write_bytes(
            ("\n".join(json.dumps(row) for row in rows) + "\n").encode())
        self.mutate_contract(lambda contract: contract["validation"].update({
            "sha256_bytes": PT.sha256_bytes(self.validation.read_bytes()),
            "rows": len(rows)}))
        self.assertIn("validation_row_hash_mismatch", self.codes(self.package()))

    def test_deps_bytes_are_checked_without_the_override(self):
        self.deps.write_bytes(b"# tampered deps after package\n")
        self.assertIn("runner_deps_hash_mismatch", self.codes(self.package()))

    def test_missing_deps_file_is_refused(self):
        self.deps.unlink()
        self.assertIn("runner_deps_missing", self.codes(self.package()))

    def test_manifest_provenance_is_required(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["inputs"].pop("evaluation_controls", None)
        manifest["inputs"].pop("source_review", None)
        self.rewrite_manifest(manifest)
        codes = self.codes(self.package())
        self.assertIn("protected_inventory_missing", codes)
        self.assertIn("source_review_missing", codes)

    def test_meta_split_never_chooses_the_fold(self):
        # The candidate-proposal keeps meta.split='train' on every row, the 70
        # validation rows included. The explicit ledger fold must still load.
        package = self.package()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertTrue(all(row["meta"]["split"] == "train"
                            for row in self.rows + self.validation_rows))
        self.assertEqual(package.facts["validation"]["rows"], 2)

    def test_train_rows_use_explicit_ledger_ids(self):
        self.build(derived=True)
        package = self.package()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertEqual(package.facts["dataset"]["rows"], 4)
        self.assertEqual(package.facts["validation"]["rows"], 2)

    def test_conflicting_validation_blocks_are_refused(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["inputs"]["validation"] = json.loads(json.dumps(
            self.contract["validation"]))
        self.rewrite_manifest(manifest)
        self.contract["validation"]["rows"] = 1
        self.write_contract()
        self.assertIn("validation_block_conflict", self.codes(self.package()))

    def test_manifest_validation_block_is_consumed(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["inputs"]["validation"] = json.loads(json.dumps(
            self.contract["validation"]))
        self.rewrite_manifest(manifest)
        self.contract.pop("validation")
        self.write_contract()
        package = self.package()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertEqual(package.validation_block["rows"], 2)

    def test_blocked_manifest_is_refused(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["status"] = "blocked"
        self.rewrite_manifest(manifest)
        self.assertIn("manifest_not_ready", self.codes(self.package()))

    def test_ready_manifest_with_failures_is_inconsistent(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["failures"] = [{"code": "x", "detail": "y"}]
        self.rewrite_manifest(manifest)
        self.assertIn("manifest_failures_present", self.codes(self.package()))

    def test_contract_must_bind_the_manifest_bytes(self):
        self.contract["manifest_sha256"] = "e" * 64
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        self.assertIn("contract_manifest_mismatch", self.codes(self.package()))

    def test_release_id_must_match(self):
        self.mutate_contract(lambda contract: contract.update({"release_id": "other"}))
        self.assertIn("release_id_mismatch", self.codes(self.package()))

    def test_runner_self_hash_must_match(self):
        other = self.tmp / "other_runner.py"
        other.write_bytes(b"# another runner\n")
        self.build(runner_path=other, dev_rows=2, validation_take=2)
        self.assertIn("runner_self_hash_mismatch", self.codes(self.package()))

    def test_deps_hash_is_required(self):
        manifest = json.loads(json.dumps(self.manifest))
        del manifest["inputs"]["runner"]["deps_sha256"]
        self.rewrite_manifest(manifest)
        self.assertIn("runner_deps_hash_missing", self.codes(self.package()))

    def test_dataset_bytes_must_match(self):
        self.corpus.write_bytes(self.corpus.read_bytes() + b"\n")
        self.assertIn("dataset_sha256_mismatch", self.codes(self.package()))

    def test_dataset_row_count_must_match(self):
        self.corpus.write_bytes(b"".join(self.corpus.read_bytes().splitlines(True)[:3]))
        codes = self.codes(self.package())
        self.assertIn("dataset_rows_mismatch", codes)

    def test_missing_tokenizer_config_pin_is_recipe_missing(self):
        manifest = json.loads(json.dumps(self.manifest))
        del manifest["recipe"]["tokenizer_config_sha256"]
        self.rewrite_manifest(manifest)
        self.assertIn("recipe_missing", self.codes(self.package()))

    def test_malformed_tokenizer_config_pin_is_recipe_unpinned(self):
        self.build(recipe_overrides={"tokenizer_config_sha256": "UNPINNED"})
        self.assertIn("recipe_unpinned", self.codes(self.package()))

    def test_missing_tokenizer_asset_pin_is_recipe_missing(self):
        manifest = json.loads(json.dumps(self.manifest))
        del manifest["recipe"]["tokenizer_assets_sha256"]
        self.rewrite_manifest(manifest)
        self.assertIn("recipe_missing", self.codes(self.package()))

    def test_malformed_tokenizer_asset_pin_is_recipe_unpinned(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["recipe"]["tokenizer_assets_sha256"] = {"tokenizer.json": "UNPINNED"}
        self.rewrite_manifest(manifest)
        self.assertIn("recipe_unpinned", self.codes(self.package()))

    def test_tokenizer_asset_traversal_is_recipe_unpinned(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["recipe"]["tokenizer_assets_sha256"] = {
            "../tokenizer.json": "1" * 64}
        self.rewrite_manifest(manifest)
        self.assertIn("recipe_unpinned", self.codes(self.package()))

    def test_tokenizer_asset_map_cannot_be_a_notes_map(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["recipe"]["tokenizer_assets_sha256"] = {
            "notes.txt": "1" * 64, "tokenizer.json": "2" * 64}
        self.rewrite_manifest(manifest)
        self.assertIn("tokenizer_asset_unknown", self.codes(self.package()))

    def test_tokenizer_asset_pin_must_name_a_representation(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["recipe"]["tokenizer_assets_sha256"] = {
            "special_tokens_map.json": "1" * 64}
        self.rewrite_manifest(manifest)
        self.assertIn("tokenizer_assets_representation_missing",
                      self.codes(self.package()))

    def test_validation_block_is_required(self):
        self.mutate_contract(lambda contract: contract.pop("validation"))
        self.assertIn("validation_missing", self.codes(self.package()))

    def test_validation_bytes_must_match(self):
        self.validation.write_bytes(self.validation.read_bytes() + b"\n")
        self.assertIn("validation_sha256_mismatch", self.codes(self.package()))

    def test_validation_row_count_must_match(self):
        self.mutate_contract(lambda contract: contract["validation"].update({"rows": 1}))
        self.assertIn("validation_rows_mismatch", self.codes(self.package()))

    def test_validation_ids_hash_must_match(self):
        self.mutate_contract(lambda contract: contract["validation"].update(
            {"ledger_ids_sha256": "f" * 64}))
        self.assertIn("validation_ids_mismatch", self.codes(self.package()))

    def test_unknown_validation_ledger_id_is_refused(self):
        rows = json.loads(json.dumps(self.validation_rows))
        rows.append(validation_row("dev-row-ghost", "ghost"))
        self.validation.write_bytes(
            ("\n".join(json.dumps(row) for row in rows) + "\n").encode())

        def mutate(contract):
            block = contract["validation"]
            block["sha256_bytes"] = PT.sha256_bytes(self.validation.read_bytes())
            block["rows"] = len(rows)
            block["ledger_ids_sha256"] = TR.sorted_hash(
                [row["meta"]["ledger_id"] for row in rows])
        self.mutate_contract(mutate)
        self.assertIn("validation_row_unknown", self.codes(self.package()))

    def test_validation_rows_must_be_dev(self):
        def mutate(entries):
            entries[4]["split"] = "train"
        self.mutate_ledger(mutate)
        self.assertIn("validation_split_not_dev", self.codes(self.package()))

    def test_validation_component_must_be_whole(self):
        self.build(dev_rows=3, validation_take=2)
        self.assertIn("validation_component_partial", self.codes(self.package()))

    def test_component_may_not_sit_in_both_splits(self):
        self.mutate_ledger(lambda entries: [entry.update({"component_id": "component:t1"})
                                            for entry in entries if entry["split"] == "dev"])
        self.mutate_contract(lambda contract: contract["validation"].update(
            {"component_ids_sha256": TR.sorted_hash(["component:t1"])}))
        codes = self.codes(self.package())
        self.assertIn("split_component_bridge", codes)
        self.assertIn("split_component_straddle", codes)

    def test_family_may_not_sit_in_both_splits(self):
        self.mutate_ledger(lambda entries: [entry.update({"family_id": "family:t1"})
                                            for entry in entries if entry["split"] == "dev"])
        self.mutate_contract(lambda contract: contract["validation"].update(
            {"family_ids_sha256": TR.sorted_hash(["family:t1"])}))
        self.assertIn("split_family_bridge", self.codes(self.package()))

    def test_train_rows_must_be_train_ready(self):
        self.mutate_ledger(lambda entries: entries[0].update({"train_ready": False}))
        self.assertIn("split_rows_not_train_ready", self.codes(self.package()))

    def test_train_row_hash_must_match_the_ledger(self):
        self.mutate_ledger(lambda entries: entries[0].update({"messages_sha256": "f" * 64}))
        self.assertIn("split_row_hash_mismatch", self.codes(self.package()))

    def test_ledger_bytes_must_match_the_manifest(self):
        self.ledger.write_bytes(self.ledger.read_bytes() + b"\n")
        self.assertIn("split_ledger_sha256_mismatch", self.codes(self.package()))

    def test_audit_bytes_must_match_the_manifest(self):
        self.audit.write_bytes(self.audit.read_bytes() + b"\n")
        self.assertIn("split_audit_sha256_mismatch", self.codes(self.package()))


class MaskTests(Fixture):
    def test_final_assistant_turn_only_is_supervised(self):
        measured, issues = self.measure(require={"answer": 1, "refusal": 1,
                                                 "gloss": 1, "history": 1})
        self.assertTrue(issues.ok, issues.failures)
        self.assertEqual(measured["family_rows"], {"answer": 1, "refusal": 1,
                                                   "gloss": 1, "history": 1})
        self.assertEqual(measured["eos_total"], 4)
        self.assertEqual(measured["eos_in_supervised"],
                         {"answer": 1, "refusal": 1, "gloss": 1, "history": 1})
        self.assertEqual(measured["user_system_supervised_tokens"], 0)
        self.assertEqual(measured["prior_assistant_supervised_tokens"], 0)
        self.assertGreater(measured["assistant_label_tokens"], 0)
        self.assertTrue(all(spot["supervised_equals_label"]
                            for spot in measured["spot_checks"]))

    def test_prior_assistant_turn_is_negative(self):
        tokenizer = FakeTokenizer()
        measured, issues = self.measure(tokenizer=tokenizer)
        self.assertTrue(issues.ok, issues.failures)
        row = next(item for item in measured["tokenized"] if item["row_index"] == 2)
        start = next(index for index, label in enumerate(row["labels"]) if label != -100)
        self.assertTrue(all(label == -100 for label in row["labels"][:start]))
        prompt = tokenizer.decode(row["input_ids"][:start])
        self.assertIn("A first-turn answer about the passage.", prompt)

    def test_every_supervised_label_equals_its_input_token(self):
        measured, issues = self.measure()
        self.assertTrue(issues.ok, issues.failures)
        for row in measured["tokenized"]:
            start = next(index for index, label in enumerate(row["labels"]) if label != -100)
            self.assertEqual(row["labels"][start:], row["input_ids"][start:])

    def test_missing_eos_is_refused(self):
        _, issues = self.measure(tokenizer=NoEosTokenizer())
        self.assertIn("row_template_shape", {item["code"] for item in issues.failures})

    def test_doubled_eos_is_refused(self):
        _, issues = self.measure(tokenizer=DoubleEosTokenizer())
        codes = {item["code"] for item in issues.failures}
        self.assertTrue({"row_template_shape", "row_scaffold_special_token"} & codes,
                        codes)

    def test_wrong_eos_pin_is_refused(self):
        _, issues = self.measure(recipe_value=recipe(assistant_eos="<|endoftext|>"))
        self.assertIn("row_template_shape", {item["code"] for item in issues.failures})

    def test_token_boundary_merge_is_refused(self):
        tokenizer = FakeTokenizer(merges={("\n", "<|im_start|>")})
        _, issues = self.measure(tokenizer=tokenizer)
        self.assertIn("row_token_boundary", {item["code"] for item in issues.failures})

    def test_overlong_row_is_refused_not_truncated(self):
        _, issues = self.measure(recipe_value=recipe(max_seq_length=10))
        self.assertIn("row_too_long", {item["code"] for item in issues.failures})

    def test_family_counts_must_match_the_manifest(self):
        _, issues = self.measure(require={"answer": 99})
        self.assertIn("mask_family_mismatch", {item["code"] for item in issues.failures})

    def test_varying_scaffold_is_refused(self):
        tokenizer = FakeTokenizer(scaffold=lambda content: "x" * len(content))
        _, issues = self.measure(tokenizer=tokenizer)
        self.assertIn("row_scaffold_varies", {item["code"] for item in issues.failures})

    def test_validation_rows_are_measured_too(self):
        issues = TR.new_issues()
        measured = TR.measure_rows(self.validation_rows, FakeTokenizer(), self.recipe,
                                   issues, "validation")
        self.assertTrue(issues.ok, issues.failures)
        self.assertEqual(measured["rows_checked"], 2)

    def test_canonical_facts_never_enter_the_training_text(self):
        rows = json.loads(json.dumps(self.rows))
        rows[0]["expected"] = {"required_facts": [{"claim": "SENTINEL-EXPECTED"}]}
        rows[0]["review"] = {"note": "SENTINEL-REVIEW"}
        tokenizer = FakeTokenizer()
        measured, issues = self.measure(
            tokenizer=tokenizer, rows=rows,
            require=self.manifest["rows"]["mask_families"])
        self.assertTrue(issues.ok, issues.failures)
        for row in measured["tokenized"]:
            text = tokenizer.decode(row["input_ids"])
            self.assertNotIn("SENTINEL-EXPECTED", text)
            self.assertNotIn("SENTINEL-REVIEW", text)

    def test_pad_batch_pads_labels_and_inputs(self):
        batch = TR.pad_batch([
            {"input_ids": [1, 2, 3], "labels": [-100, -100, 3]},
            {"input_ids": [4], "labels": [4]}], pad_token_id=7, max_seq_length=8)
        self.assertEqual(batch["input_ids"], [[1, 2, 3], [4, 7, 7]])
        self.assertEqual(batch["labels"], [[-100, -100, 3], [4, -100, -100]])
        self.assertEqual(batch["attention_mask"], [[1, 1, 1], [1, 0, 0]])

    def test_pad_batch_refuses_overflow(self):
        with self.assertRaises(ValueError):
            TR.pad_batch([{"input_ids": [1, 2], "labels": [1, 2]}],
                         pad_token_id=7, max_seq_length=1)


class LedgerResolutionTests(unittest.TestCase):
    """Explicit row ids beat line numbers; meta.split is never consulted."""

    def setUp(self):
        row_hash = TR.row_messages_sha256({})
        self.entry = {"id": "r1", "source_path": "/x/train.jsonl", "line": 99,
                      "messages_sha256": row_hash}
        self.line_entry = {"id": "line-1", "source_path": "/x/train.jsonl", "line": 1,
                           "messages_sha256": row_hash}
        self.path_index = {("/x/train.jsonl", 1): self.line_entry}
        self.by_id = {"r1": self.entry}

    def resolve(self, row, issues):
        return TR.resolve_train_entry(row, 1, self.path_index, self.by_id,
                                      "/x/train.jsonl", issues)

    def test_explicit_id_wins_over_the_line(self):
        issues = TR.new_issues()
        self.assertIs(self.resolve({"meta": {"ledger_id": "r1",
                                             "split": "dev"}}, issues), self.entry)
        self.assertTrue(issues.ok, issues.failures)

    def test_id_with_different_content_is_refused(self):
        self.by_id["r1"] = dict(self.entry, messages_sha256="f" * 64)
        issues = TR.new_issues()
        self.assertIsNone(self.resolve({"meta": {"ledger_id": "r1"}}, issues))
        self.assertIn("split_row_id_content_mismatch",
                      {item["code"] for item in issues.failures})

    def test_unknown_id_is_refused(self):
        issues = TR.new_issues()
        self.assertIsNone(self.resolve({"meta": {"ledger_id": "ghost"}}, issues))
        self.assertIn("split_row_unknown", {item["code"] for item in issues.failures})

    def test_id_is_authoritative_across_paths(self):
        # A derived train file may not be the ledger's source file; the id is
        # the membership, and the messages hash is checked separately.
        self.by_id["r1"] = dict(self.entry, source_path="/other/train.jsonl")
        issues = TR.new_issues()
        self.assertIs(self.resolve({"meta": {"ledger_id": "r1"}}, issues),
                      self.by_id["r1"])
        self.assertTrue(issues.ok, issues.failures)

    def test_missing_id_falls_back_to_the_line(self):
        issues = TR.new_issues()
        self.assertIs(self.resolve({"meta": {"split": "dev"}}, issues), self.line_entry)
        self.assertTrue(issues.ok, issues.failures)


class InventoryTests(Fixture):
    def test_train_question_overlapping_the_protected_union_is_refused(self):
        row = {"messages": [{"role": "user",
                             "content": "Question: protected synthetic question\n\nPassages: x"}]}
        issues = TR.new_issues()
        facts = TR.verify_inventory(self.contract, self.manifest, [row], [],
                                    self.contract["validation"], issues)
        self.assertIn("protected_question_overlap",
                      {item["code"] for item in issues.failures})
        self.assertEqual(facts["overlaps"], 1)

    def test_unique_messages_hash_resolves_and_duplicates_are_ambiguous(self):
        row = {"messages": [{"role": "user", "content": "x"}]}
        digest = TR.row_messages_sha256(row)
        issues = TR.new_issues()
        entry = TR.unique_message_entry(row, {"a": {"id": "a", "messages_sha256": digest}},
                                        issues, "test_ambiguous", "row")
        self.assertEqual(entry["id"], "a")
        self.assertTrue(issues.ok, issues.failures)
        issues = TR.new_issues()
        TR.unique_message_entry(row, {"a": {"id": "a", "messages_sha256": digest},
                                      "b": {"id": "b", "messages_sha256": digest}},
                                issues, "test_ambiguous", "row")
        self.assertIn("test_ambiguous", {item["code"] for item in issues.failures})


class ProducerTests(Fixture):
    """The hash is of the pinned file's bytes, not a reserialized object."""

    def hub(self, path):
        import types
        return types.SimpleNamespace(hf_hub_download=lambda **kwargs: str(path))

    def test_resolve_cached_hashes_the_actual_file_bytes(self):
        revision = "a" * 40
        snapshot = self.tmp / "snapshots" / revision
        snapshot.mkdir(parents=True)
        payload = b'{"chat_template": "pinned bytes"}'
        (snapshot / "tokenizer_config.json").write_bytes(payload)
        issues = TR.new_issues()
        with unittest.mock.patch.dict(sys.modules,
                                     {"huggingface_hub": self.hub(snapshot / "tokenizer_config.json")}):
            resolved = TR.resolve_cached("org/model", "tokenizer_config.json",
                                         revision, issues)
        self.assertTrue(issues.ok, issues.failures)
        self.assertEqual(resolved["sha256"], PT.sha256_bytes(payload))
        self.assertEqual(resolved["revision"], revision)
        self.assertEqual(resolved["path"], str(snapshot / "tokenizer_config.json"))

    def test_resolve_cached_rejects_a_different_snapshot(self):
        snapshot = self.tmp / "snapshots" / ("f" * 40)
        snapshot.mkdir(parents=True)
        (snapshot / "tokenizer_config.json").write_bytes(b"{}")
        issues = TR.new_issues()
        with unittest.mock.patch.dict(sys.modules,
                                     {"huggingface_hub": self.hub(snapshot / "tokenizer_config.json")}):
            TR.resolve_cached("org/model", "tokenizer_config.json", "a" * 40, issues)
        self.assertIn("hub_snapshot_mismatch", {item["code"] for item in issues.failures})

    def test_preflight_report_carries_the_runtime_file_hash(self):
        package = self.package()
        issues = TR.new_issues()
        train = TR.measure_rows(self.rows, FakeTokenizer(), self.recipe, issues, "train")
        validation = TR.measure_rows(self.validation_rows, FakeTokenizer(), self.recipe,
                                     issues, "validation")
        self.assertTrue(issues.ok, issues.failures)
        identity = {"chat_template_sha256": self.recipe["tokenizer_chat_template_sha256"],
                    "tokenizer_config_sha256": "f" * 64,
                    "tokenizer_config_path": "/cache/snapshots/x/tokenizer_config.json"}
        report = TR.build_preflight_report(package, self.recipe, train, validation,
                                          identity, [], {"gpu": "A100"})
        self.assertEqual(report["tokenizer_config_sha256"], "f" * 64)
        self.assertNotEqual(report["tokenizer_config_sha256"],
                            self.recipe["tokenizer_config_sha256"])


class IdentityTests(Fixture):
    def proof(self):
        snapshot = self.tmp / "snapshots" / ("a" * 40)
        snapshot.mkdir(parents=True, exist_ok=True)
        return {"status": "verified", "snapshot_path": str(snapshot),
                "requested_revision": "a" * 40, "resolved_revision": "a" * 40,
                "files": {"config.json": {"sha256": "e" * 64},
                          "tokenizer_config.json": {"sha256": "d" * 64},
                          "tokenizer.json": {"sha256": "1" * 64},
                          "special_tokens_map.json": {"sha256": "2" * 64},
                          "model.safetensors": {"sha256": "f" * 64}},
                "index": None}

    def resolved(self, **overrides):
        value = {"commit": "a" * 40, "config_revision": "a" * 40,
                 "tokenizer_revision": "a" * 40,
                 "tokenizer_config_sha256": "d" * 64, "config_sha256": "e" * 64,
                 "tokenizer_assets_sha256": {"tokenizer.json": "1" * 64,
                                             "special_tokens_map.json": "2" * 64},
                 "weights_sha256": {"model.safetensors": "f" * 64},
                 "loader_input": str(self.tmp / "snapshots" / ("a" * 40)),
                 "loader_input_argument": str(self.tmp / "snapshots" / ("a" * 40)),
                 "artifact_proof": self.proof()}
        value.update(overrides)
        return value

    def identity(self, tokenizer=None, recipe_value=None, resolved=None,
                 model=None, issues=None):
        issues = issues or TR.new_issues()
        TR.verify_identity(tokenizer or FakeTokenizer(), recipe_value or self.recipe,
                           model or self.contract["model"], resolved or self.resolved(),
                           issues)
        return issues

    def test_good_identity_passes(self):
        issues = TR.new_issues()
        measured = TR.verify_identity(FakeTokenizer(), self.recipe,
                                      self.contract["model"], self.resolved(), issues)
        self.assertTrue(issues.ok, issues.failures)
        self.assertEqual(measured["commit"], "a" * 40)
        self.assertEqual(measured["config_revision"], "a" * 40)
        self.assertEqual(measured["tokenizer_revision"], "a" * 40)
        self.assertEqual(measured["tokenizer_config_sha256"], "d" * 64)

    def test_resolved_tokenizer_revision_must_match(self):
        approved = dict(self.recipe, tokenizer_revision="b" * 40)
        issues = self.identity(recipe_value=approved)
        self.assertIn("resolved_revision_mismatch",
                      {item["code"] for item in issues.failures})
        self.assertIn("tokenizer_revision_unsupported",
                      {item["code"] for item in issues.failures})

    def test_known_good_tokenizer_config_hash_agrees(self):
        expected = REAL_TOKENIZER_CONFIG_SHA
        issues = self.identity(recipe_value=recipe(tokenizer_config_sha256=expected),
                               resolved=self.resolved(tokenizer_config_sha256=expected))
        self.assertTrue(issues.ok, issues.failures)

    def test_valid_but_wrong_tokenizer_config_hash_is_refused(self):
        issues = self.identity(resolved=self.resolved(
            tokenizer_config_sha256="f" * 64))
        self.assertIn("tokenizer_config_hash_mismatch",
                      {item["code"] for item in issues.failures})

    def test_wrong_template_is_refused(self):
        tokenizer = FakeTokenizer(template="a different template")
        self.assertIn("tokenizer_template_mismatch",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})

    def test_dead_tokenizer_is_refused_by_identity(self):
        issues = self.identity(tokenizer=DeadTokenizer())
        self.assertIn("tokenizer_dead", {item["code"] for item in issues.failures})

    def test_tokenizer_asset_hash_mismatch_is_refused(self):
        issues = self.identity(resolved=self.resolved(tokenizer_assets_sha256={
            "tokenizer.json": "0" * 64, "special_tokens_map.json": "2" * 64}))
        self.assertIn("tokenizer_asset_hash_mismatch",
                      {item["code"] for item in issues.failures})

    def test_wrong_eos_is_refused(self):
        tokenizer = FakeTokenizer(eos="<|endoftext|>")
        self.assertIn("tokenizer_eos_mismatch",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})

    def test_pad_token_zero_is_refused(self):
        tokenizer = FakeTokenizer(pad_id=0)
        self.assertIn("pad_token_zero",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})

    def test_pad_token_mismatch_is_refused(self):
        tokenizer = FakeTokenizer(pad="<pad>", pad_id=9)
        self.assertIn("pad_token_mismatch",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})

    def test_resolved_revision_must_match(self):
        issues = self.identity(resolved=self.resolved(commit="f" * 40))
        self.assertIn("base_revision_mismatch", {item["code"] for item in issues.failures})

    def test_empty_loader_commit_passes_only_with_verified_artifacts(self):
        issues = TR.new_issues()
        measured = TR.verify_identity(FakeTokenizer(), self.recipe,
                                      self.contract["model"],
                                      self.resolved(commit=""), issues)
        self.assertTrue(issues.ok, issues.failures)
        self.assertEqual(measured["commit"], "")
        self.assertIsNone(measured["loader_commit_hash"])
        self.assertTrue(measured["snapshot_used_as_loader_input"])

    def test_legacy_empty_commit_without_artifact_proof_is_refused(self):
        issues = TR.new_issues()
        reversed_value = self.resolved(commit="")
        reversed_value.pop("artifact_proof")
        reversed_value.pop("weights_sha256")
        TR.verify_identity(FakeTokenizer(), self.recipe, self.contract["model"],
                           reversed_value, issues)
        codes = {item["code"] for item in issues.failures}
        self.assertIn("base_revision_unresolved", codes)
        self.assertIn("base_artifact_unverified", codes)

    def test_proof_must_be_the_loader_input(self):
        issues = self.identity(resolved=self.resolved(
            loader_input=str(self.tmp / "other" / ("a" * 40))))
        self.assertIn("base_artifact_unverified",
                      {item["code"] for item in issues.failures})

    def test_wrong_weight_pin_is_refused(self):
        approved = dict(self.recipe, weights_sha256={"model.safetensors": "0" * 64})
        issues = self.identity(recipe_value=approved)
        self.assertIn("base_weights_hash_mismatch",
                      {item["code"] for item in issues.failures})

    def test_thinking_must_be_honored(self):
        tokenizer = IgnoringThinkingTokenizer()
        self.assertIn("template_thinking_unsupported",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})

    def test_unknown_thinking_kwarg_is_refused(self):
        tokenizer = FakeTokenizer(reject_thinking_kwarg=True)
        self.assertIn("template_kwarg_unsupported",
                      {item["code"] for item in self.identity(tokenizer=tokenizer).failures})


class SnapshotTests(Fixture):
    """Config and every weight file are pinned and verified before the loader runs."""

    REVISION = "a" * 40
    WEIGHT = "model.safetensors-00001-of-00001.safetensors"
    CONFIG = b'{"model_type":"qwen3_5","pinned":true}\n'
    TOKENIZER = b'{"chat_template":"pinned tokenizer config"}\n'
    TOKENIZER_JSON = b'{"model":{"type":"BPE"},"pinned":"tokenizer.json"}\n'
    SPECIAL_MAP = b'{"eos_token":"<|im_end|>"}\n'
    WEIGHTS = b"fake weight bytes, not a checkpoint\n"

    def setUp(self):
        super().setUp()
        self.snapshot_dir = self.tmp / "hub" / "snapshots" / self.REVISION
        self.snapshot_dir.mkdir(parents=True)
        (self.snapshot_dir / "config.json").write_bytes(self.CONFIG)
        (self.snapshot_dir / "tokenizer_config.json").write_bytes(self.TOKENIZER)
        (self.snapshot_dir / "tokenizer.json").write_bytes(self.TOKENIZER_JSON)
        (self.snapshot_dir / "special_tokens_map.json").write_bytes(self.SPECIAL_MAP)
        (self.snapshot_dir / self.WEIGHT).write_bytes(self.WEIGHTS)
        self.write_index([self.WEIGHT])
        self.build(recipe_overrides=self.pins())

    def pins(self):
        pins = {"config_sha256": PT.sha256_bytes(self.CONFIG),
                "tokenizer_config_sha256": PT.sha256_bytes(self.TOKENIZER),
                "tokenizer_assets_sha256": {
                    "tokenizer.json": PT.sha256_bytes(self.TOKENIZER_JSON),
                    "special_tokens_map.json": PT.sha256_bytes(self.SPECIAL_MAP)},
                "weights_sha256": {self.WEIGHT: PT.sha256_bytes(self.WEIGHTS)}}
        index = self.snapshot_dir / PT.WEIGHTS_INDEX_NAME
        if index.exists():
            pins["weights_index_sha256"] = PT.sha256_bytes(index.read_bytes())
        return pins

    def write_index(self, shards, name="model.safetensors.index.json"):
        weight_map = {"tensor-%d" % index: shard for index, shard in enumerate(shards)}
        path = self.snapshot_dir / name
        path.write_text(json.dumps({"metadata": {}, "weight_map": weight_map}),
                        encoding="utf-8")
        return path

    def hub(self, index_online_only=False, offline_miss=()):
        calls = []
        mapping = {"config.json": self.snapshot_dir / "config.json",
                   "tokenizer_config.json": self.snapshot_dir / "tokenizer_config.json",
                   "tokenizer.json": self.snapshot_dir / "tokenizer.json",
                   "special_tokens_map.json": self.snapshot_dir / "special_tokens_map.json",
                   PT.WEIGHTS_INDEX_NAME: self.snapshot_dir / PT.WEIGHTS_INDEX_NAME}
        for name in self.recipe["weights_sha256"]:
            mapping[name] = self.snapshot_dir / name

        def download(**kwargs):
            calls.append(dict(kwargs))
            name = kwargs["filename"]
            if name == PT.WEIGHTS_INDEX_NAME and index_online_only \
                    and kwargs.get("local_files_only"):
                raise FileNotFoundError("the index is not in the offline cache: %s" % name)
            if name in offline_miss and kwargs.get("local_files_only"):
                raise FileNotFoundError("not in the offline cache: %s" % name)
            if name not in mapping or not Path(mapping[name]).exists():
                raise FileNotFoundError("not in the offline cache: %s" % name)
            return str(mapping[name])

        return types.SimpleNamespace(hf_hub_download=download), calls

    def fake_stack(self, commit="", resolved_name=None, fail=False, before=None,
                   call_callback=True):
        loader_calls = []

        class FastLanguageModel:
            @staticmethod
            def from_pretrained(**kwargs):
                loader_calls.append(dict(kwargs))
                if before is not None:
                    before()
                if fail:
                    raise RuntimeError("the fake loader refused")
                callback = kwargs.get("on_model_resolved")
                if callback is not None and call_callback:
                    callback(resolved_name if resolved_name is not None
                             else kwargs["model_name"])
                config = types.SimpleNamespace()
                if commit is not None:
                    config._commit_hash = commit
                return (types.SimpleNamespace(config=config),
                        types.SimpleNamespace(tokenizer=FakeTokenizer()))

        torch_module = types.ModuleType("torch")
        torch_module.cuda = types.SimpleNamespace(is_available=lambda: True)
        return (torch_module, types.SimpleNamespace(FastLanguageModel=FastLanguageModel),
                loader_calls)

    def run_session(self, commit="", resolved_name=None, fail=False, before=None,
                    call_callback=True, allow_download=False, index_online_only=False,
                    offline_miss=()):
        hub, hub_calls = self.hub(index_online_only=index_online_only,
                                  offline_miss=offline_miss)
        torch_module, unsloth, loader_calls = self.fake_stack(
            commit, resolved_name, fail, before=before, call_callback=call_callback)
        state = {}
        with unittest.mock.patch.dict(sys.modules,
                                      {"huggingface_hub": hub, "torch": torch_module,
                                       "unsloth": unsloth}):
            package = self.package()
            log = TR.EventLog(self.tmp / "events.jsonl")
            try:
                session = TR.load_session(package, log, package.facts["recipe"],
                                          allow_download=allow_download,
                                          identity_path=self.tmp / "identity-measurement.json",
                                          identity_state=state)
            finally:
                log.close()
        return package, session, state, loader_calls, hub_calls

    def resolve(self, recipe_value=None, allow_download=False):
        issues = TR.new_issues()
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            proof = TR.resolve_snapshot(recipe_value or self.recipe, issues,
                                        allow_download=allow_download)
        return proof, issues, calls

    def codes(self, package):
        return {failure["code"] for failure in package.issues.failures}

    def test_pinned_snapshot_is_verified_and_becomes_the_loader_input(self):
        package, session, state, loader_calls, hub_calls = self.run_session()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        self.assertEqual(loader_calls[0]["model_name"], str(self.snapshot_dir))
        self.assertIs(loader_calls[0]["local_files_only"], True)
        self.assertIs(loader_calls[0]["use_safetensors"], True)
        self.assertIs(loader_calls[0]["use_exact_model_name"], True)
        self.assertNotIn("revision", loader_calls[0])
        identity = session["identity"]
        self.assertEqual(identity["config_sha256"], self.recipe["config_sha256"])
        self.assertEqual(identity["weights_sha256"], self.recipe["weights_sha256"])
        self.assertEqual(identity["snapshot_path"], str(self.snapshot_dir))

    def test_empty_loader_commit_passes_with_verified_local_snapshot(self):
        package, session, state, loader_calls, _ = self.run_session(commit="")
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        identity = session["identity"]
        self.assertEqual(identity["commit"], "")
        self.assertIsNone(identity["loader_commit_hash"])
        self.assertTrue(identity["snapshot_used_as_loader_input"])
        self.assertEqual(identity["weights_index_shards"], [self.WEIGHT])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["phase"], "post_load")
        self.assertEqual(saved["measured"]["weights_sha256"][self.WEIGHT],
                         PT.sha256_bytes(self.WEIGHTS))
        self.assertIsNone(saved["loader"]["commit_hash"])

    def test_absent_private_field_is_recorded_not_filled_in(self):
        package, session, state, _, _ = self.run_session(commit=None)
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertEqual(session["identity"]["commit"], "")
        self.assertIsNone(session["identity"]["loader_commit_hash"])

    def test_wrong_config_bytes_refuse_before_the_loader(self):
        (self.snapshot_dir / "config.json").write_bytes(b'{"tampered":true}\n')
        package, session, state, loader_calls, _ = self.run_session()
        self.assertIn("model_config_hash_mismatch", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["status"], "refused")
        self.assertNotEqual(saved["measured"]["config_sha256"],
                            saved["pins"]["config_sha256"])

    def test_wrong_weight_bytes_refuse_before_the_loader(self):
        (self.snapshot_dir / self.WEIGHT).write_bytes(b"other weight bytes")
        package, session, state, loader_calls, _ = self.run_session()
        self.assertIn("base_weights_hash_mismatch", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])

    def test_missing_weight_file_refuses(self):
        (self.snapshot_dir / self.WEIGHT).unlink()
        package, session, _, loader_calls, _ = self.run_session()
        self.assertIn("hub_file_missing", self.codes(package))
        self.assertEqual(loader_calls, [])

    def test_missing_weight_pin_refuses(self):
        issues = TR.new_issues()
        unpinned = dict(self.recipe)
        unpinned.pop("weights_sha256")
        proof = TR.resolve_snapshot(unpinned, issues)
        self.assertIn("base_weights_pin_missing",
                      {item["code"] for item in issues.failures})
        self.assertEqual(proof["status"], "failed")

    def test_missing_config_pin_refuses(self):
        issues = TR.new_issues()
        unpinned = dict(self.recipe)
        unpinned.pop("config_sha256")
        TR.resolve_snapshot(unpinned, issues)
        self.assertIn("model_config_pin_missing",
                      {item["code"] for item in issues.failures})

    def test_missing_tokenizer_asset_pin_refuses_before_any_lookup(self):
        issues = TR.new_issues()
        unpinned = dict(self.recipe)
        unpinned.pop("tokenizer_assets_sha256")
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            proof = TR.resolve_snapshot(unpinned, issues)
        self.assertIn("tokenizer_assets_pin_missing",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])
        self.assertEqual(proof["status"], "failed")

    def test_malformed_tokenizer_asset_pin_refuses_before_any_lookup(self):
        issues = TR.new_issues()
        pinned = dict(self.recipe)
        pinned["tokenizer_assets_sha256"] = {"tokenizer.json": "not-a-sha256"}
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("tokenizer_asset_pin_invalid",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_tokenizer_asset_traversal_refuses_before_any_lookup(self):
        issues = TR.new_issues()
        pinned = dict(self.recipe)
        pinned["tokenizer_assets_sha256"] = {"../tokenizer.json": "1" * 64}
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("tokenizer_asset_pin_path_invalid",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_notes_file_cannot_stand_in_for_the_vocabulary(self):
        issues = TR.new_issues()
        pinned = dict(self.recipe)
        pinned["tokenizer_assets_sha256"] = {"notes.txt": "1" * 64,
                                             "tokenizer.json": "2" * 64}
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("tokenizer_asset_pin_path_invalid",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_tokenizer_asset_map_must_name_a_representation(self):
        issues = TR.new_issues()
        pinned = dict(self.recipe)
        pinned["tokenizer_assets_sha256"] = {"special_tokens_map.json": "1" * 64}
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("tokenizer_assets_representation_missing",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_missing_tokenizer_asset_refuses_before_the_loader(self):
        (self.snapshot_dir / "tokenizer.json").unlink()
        package, session, state, loader_calls, _ = self.run_session()
        self.assertIn("hub_file_missing", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["status"], "refused")
        self.assertEqual(saved["pins"]["tokenizer_assets_sha256"]["tokenizer.json"],
                         PT.sha256_bytes(self.TOKENIZER_JSON))
        self.assertNotIn("tokenizer.json", saved["measured"]["tokenizer_assets_sha256"])

    def test_changed_tokenizer_asset_refuses_before_the_loader(self):
        (self.snapshot_dir / "tokenizer.json").write_bytes(b'{"tampered":true}\n')
        package, session, state, loader_calls, _ = self.run_session()
        self.assertIn("tokenizer_asset_hash_mismatch", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        measured = saved["measured"]["tokenizer_assets_sha256"]["tokenizer.json"]
        expected = saved["pins"]["tokenizer_assets_sha256"]["tokenizer.json"]
        self.assertNotEqual(measured, expected)
        self.assertEqual(measured, PT.sha256_bytes(b'{"tampered":true}\n'))

    def test_unpinned_fallback_representation_refuses(self):
        (self.snapshot_dir / "vocab.json").write_bytes(b'{"a":1}\n')
        package, session, _, loader_calls, _ = self.run_session()
        self.assertIn("unpinned_tokenizer_representation", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])

    def test_tokenizer_assets_are_resolved_at_the_pinned_revision(self):
        package, session, state, loader_calls, hub_calls = self.run_session()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        for name in ("tokenizer.json", "special_tokens_map.json"):
            calls = [call for call in hub_calls if call["filename"] == name]
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["revision"], self.REVISION)
            self.assertIs(calls[0]["local_files_only"], True)
        identity = session["identity"]
        self.assertEqual(identity["tokenizer_assets_sha256"],
                         self.recipe["tokenizer_assets_sha256"])

    def test_tokenizer_asset_cache_miss_downloads_only_the_pinned_revision(self):
        package, session, state, loader_calls, hub_calls = self.run_session(
            allow_download=True, offline_miss={"tokenizer.json"})
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        asset_calls = [call for call in hub_calls
                       if call["filename"] == "tokenizer.json"]
        self.assertEqual(len(asset_calls), 2)
        self.assertIs(asset_calls[0]["local_files_only"], True)
        self.assertIs(asset_calls[1]["local_files_only"], False)
        self.assertEqual({call["revision"] for call in asset_calls}, {self.REVISION})
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["measured"]["tokenizer_assets_sha256"]["tokenizer.json"],
                         self.recipe["tokenizer_assets_sha256"]["tokenizer.json"])

    def test_weight_pin_path_traversal_refuses_before_any_lookup(self):
        issues = TR.new_issues()
        pinned = dict(self.recipe)
        pinned["weights_sha256"] = {"../model.safetensors": "f" * 64}
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("weights_pin_path_invalid",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_unpinned_alternate_weights_refuse(self):
        (self.snapshot_dir / "model-00002-of-00002.bin").write_bytes(b"alternate")
        proof, issues, _ = self.resolve()
        self.assertIn("unpinned_weight_file",
                      {item["code"] for item in issues.failures})

    def test_index_shard_set_must_match_the_pins(self):
        self.write_index([self.WEIGHT, "model-00002-of-00002.safetensors"])
        proof, issues, _ = self.resolve()
        self.assertIn("weights_index_mismatch",
                      {item["code"] for item in issues.failures})

    def test_multi_shard_pins_require_an_index(self):
        pinned = dict(self.recipe)
        pinned["weights_sha256"] = {self.WEIGHT: PT.sha256_bytes(self.WEIGHTS),
                                    "model-00002-of-00002.safetensors": "f" * 64}
        (self.snapshot_dir / "model.safetensors.index.json").unlink()
        proof, issues, _ = self.resolve(pinned)
        self.assertIn("weights_index_missing",
                      {item["code"] for item in issues.failures})
        self.assertEqual(proof["status"], "failed")

    def test_index_that_does_not_parse_refuses(self):
        (self.snapshot_dir / "model.safetensors.index.json").write_text("{not json",
                                                                       encoding="utf-8")
        proof, issues, _ = self.resolve()
        self.assertIn("weights_index_invalid",
                      {item["code"] for item in issues.failures})

    def test_structural_index_pin_is_required_for_a_noncanonical_single_shard(self):
        unpinned = dict(self.recipe)
        unpinned.pop("weights_index_sha256")
        issues = TR.new_issues()
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            proof = TR.resolve_snapshot(unpinned, issues)
        self.assertIn("weights_index_pin_missing",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])
        self.assertEqual(proof["status"], "failed")

    def test_bad_index_pin_is_refused_before_any_lookup(self):
        pinned = dict(self.recipe)
        pinned["weights_index_sha256"] = "not-a-sha256"
        issues = TR.new_issues()
        hub, calls = self.hub()
        with unittest.mock.patch.dict(sys.modules, {"huggingface_hub": hub}):
            TR.resolve_snapshot(pinned, issues)
        self.assertIn("weights_index_pin_invalid",
                      {item["code"] for item in issues.failures})
        self.assertEqual(calls, [])

    def test_pinned_index_is_measured_at_the_exact_revision(self):
        package, session, state, loader_calls, hub_calls = self.run_session()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        index_calls = [call for call in hub_calls
                       if call["filename"] == PT.WEIGHTS_INDEX_NAME]
        self.assertEqual(len(index_calls), 1)
        self.assertEqual(index_calls[0]["revision"], self.REVISION)
        self.assertIs(index_calls[0]["local_files_only"], True)
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["pins"]["weights_index_sha256"],
                         self.recipe["weights_index_sha256"])
        self.assertEqual(saved["measured"]["weights_index_sha256"],
                         self.recipe["weights_index_sha256"])
        self.assertEqual(saved["measured"]["weights_index_shards"], [self.WEIGHT])
        self.assertEqual(saved["measured"]["loader_input"], str(self.snapshot_dir))

    def test_missing_index_file_refuses_before_the_loader(self):
        (self.snapshot_dir / PT.WEIGHTS_INDEX_NAME).unlink()
        package, session, state, loader_calls, _ = self.run_session()
        self.assertIn("weights_index_missing", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["status"], "refused")
        self.assertEqual(saved["pins"]["weights_index_sha256"],
                         self.recipe["weights_index_sha256"])
        self.assertIsNone(saved["measured"]["weights_index_sha256"])

    def test_index_mapping_mutation_with_the_same_shards_is_refused(self):
        (self.snapshot_dir / PT.WEIGHTS_INDEX_NAME).write_text(json.dumps(
            {"metadata": {}, "weight_map": {"different_tensor": self.WEIGHT}}),
            encoding="utf-8")
        package, session, _, loader_calls, _ = self.run_session()
        self.assertIn("weights_index_hash_mismatch", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertNotEqual(saved["measured"]["weights_index_sha256"],
                            saved["pins"]["weights_index_sha256"])
        self.assertEqual(saved["measured"]["weights_index_sha256"], PT.sha256_bytes(
            (self.snapshot_dir / PT.WEIGHTS_INDEX_NAME).read_bytes()))

    def test_index_cache_miss_downloads_only_the_pinned_revision(self):
        package, session, state, loader_calls, hub_calls = self.run_session(
            allow_download=True, index_online_only=True)
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        index_calls = [call for call in hub_calls
                       if call["filename"] == PT.WEIGHTS_INDEX_NAME]
        self.assertEqual(len(index_calls), 2)
        self.assertIs(index_calls[0]["local_files_only"], True)
        self.assertIs(index_calls[1]["local_files_only"], False)
        self.assertEqual({call["revision"] for call in index_calls}, {self.REVISION})
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["measured"]["weights_index_sha256"],
                         self.recipe["weights_index_sha256"])

    def test_canonical_single_weight_needs_no_index_pin(self):
        (self.snapshot_dir / self.WEIGHT).unlink()
        (self.snapshot_dir / PT.WEIGHTS_INDEX_NAME).unlink()
        weights = b"canonical single checkpoint\n"
        (self.snapshot_dir / "model.safetensors").write_bytes(weights)
        pins = self.pins()
        pins["weights_sha256"] = {"model.safetensors": PT.sha256_bytes(weights)}
        pins.pop("weights_index_sha256", None)
        self.build(recipe_overrides=pins)
        package, session, state, loader_calls, hub_calls = self.run_session()
        self.assertTrue(package.issues.ok, package.issues.failures)
        self.assertIsNotNone(session)
        self.assertEqual([call for call in hub_calls
                          if call["filename"] == PT.WEIGHTS_INDEX_NAME], [])
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertIsNone(saved["pins"]["weights_index_sha256"])
        self.assertIsNone(saved["measured"]["weights_index_sha256"])

    def test_unpinned_index_file_is_refused(self):
        (self.snapshot_dir / self.WEIGHT).unlink()
        weights = b"canonical single checkpoint\n"
        (self.snapshot_dir / "model.safetensors").write_bytes(weights)
        pins = self.pins()
        pins["weights_sha256"] = {"model.safetensors": PT.sha256_bytes(weights)}
        pins.pop("weights_index_sha256", None)
        self.build(recipe_overrides=pins)
        package, session, _, loader_calls, _ = self.run_session()
        self.assertIn("weights_index_unpinned", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(loader_calls, [])

    def test_silent_callback_is_refused_not_inferred(self):
        package, session, state, loader_calls, _ = self.run_session(call_callback=False)
        self.assertIn("loader_resolution_unobserved", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(len(loader_calls), 1)
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["status"], "refused")
        self.assertIsNone(saved["loader"]["resolved_name"])
        self.assertEqual(saved["loader"]["input_argument"], str(self.snapshot_dir))
        self.assertIsNone(saved["measured"]["loader_input"])

    def test_nonempty_wrong_loader_commit_still_refuses(self):
        package, session, state, loader_calls, _ = self.run_session(commit="f" * 40)
        self.assertIn("base_revision_mismatch", self.codes(package))
        self.assertEqual(loader_calls[0]["model_name"], str(self.snapshot_dir))
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["loader"]["commit_hash"], "f" * 40)

    def test_legacy_manifest_without_artifact_pins_cannot_load(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["recipe"].pop("config_sha256")
        manifest["recipe"].pop("weights_sha256")
        self.rewrite_manifest(manifest)
        package = self.package()
        self.assertFalse(package.issues.ok)
        self.assertIn("recipe_missing", self.codes(package))

    def test_loader_remap_is_refused(self):
        wrong = str(self.tmp / "wrong-snapshot")
        package, session, _, loader_calls, _ = self.run_session(resolved_name=wrong)
        self.assertIn("loader_input_mismatch", self.codes(package))
        self.assertIsNone(session)
        self.assertEqual(len(loader_calls), 1)
        self.assertEqual(loader_calls[0]["model_name"], str(self.snapshot_dir))
        saved = json.loads((self.tmp / "identity-measurement.json").read_text())
        self.assertEqual(saved["loader"]["resolved_name"], wrong)
        self.assertEqual(saved["measured"]["loader_input"], wrong)

    def test_weight_hash_is_streamed(self):
        target = self.tmp / "large.safetensors"
        target.write_bytes(b"x" * 3000)
        sizes = []
        real_open = builtins.open

        class Spy:
            def __init__(self, handle):
                self.handle = handle

            def read(self, size=-1):
                sizes.append(size)
                return self.handle.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

        def fake_open(path, mode="r", *args, **kwargs):
            return Spy(real_open(path, mode, *args, **kwargs)) \
                if Path(path) == target else real_open(path, mode, *args, **kwargs)

        with unittest.mock.patch("builtins.open", fake_open):
            digest, size = TR.stream_file_sha256(target, chunk_size=1024)
        self.assertEqual(size, 3000)
        self.assertEqual(digest, PT.sha256_bytes(b"x" * 3000))
        self.assertTrue(sizes)
        self.assertEqual(max(sizes), 1024)

    def test_preflight_failure_keeps_partial_identity_and_events(self):
        hub, _ = self.hub()
        out = self.tmp / "preflight-out"
        seen = {}

        def before_load():
            path = out / "identity-measurement.json"
            seen["exists"] = path.exists()
            seen["payload"] = json.loads(path.read_text()) if path.exists() else {}

        torch_module, unsloth, loader_calls = self.fake_stack(fail=True,
                                                              before=before_load)
        with unittest.mock.patch.dict(sys.modules,
                                      {"huggingface_hub": hub, "torch": torch_module,
                                       "unsloth": unsloth}), \
                contextlib.redirect_stdout(io.StringIO()):
            code = TR.main(["preflight", "--manifest", str(self.manifest_path),
                            "--contract", str(self.contract_path), "--out", str(out)])
        self.assertEqual(code, 2)
        self.assertEqual(len(loader_calls), 1)
        self.assertEqual(loader_calls[0]["model_name"], str(self.snapshot_dir))
        self.assertTrue(seen["exists"])
        self.assertEqual(seen["payload"]["measured"]["config_sha256"],
                         self.recipe["config_sha256"])
        self.assertEqual(seen["payload"]["measured"]["weights_sha256"][self.WEIGHT],
                         PT.sha256_bytes(self.WEIGHTS))
        identity = json.loads((out / "identity-measurement.json").read_text())
        self.assertEqual(identity["status"], "refused")
        self.assertEqual(identity["measured"]["config_sha256"],
                         self.recipe["config_sha256"])
        self.assertEqual(identity["measured"]["weights_sha256"][self.WEIGHT],
                         PT.sha256_bytes(self.WEIGHTS))
        self.assertEqual(identity["loader"]["input_argument"], str(self.snapshot_dir))
        self.assertIsNone(identity["loader"]["commit_hash"])
        failure = json.loads((out / "preflight-failure.json").read_text())
        self.assertIn("traceback", failure)
        self.assertEqual(failure["identity"]["measured"]["config_sha256"],
                         self.recipe["config_sha256"])
        self.assertTrue((out / "events.jsonl").exists())


class ReportTests(Fixture):
    def setUp(self):
        super().setUp()
        self.issues = TR.new_issues()
        self.train = TR.measure_rows(self.rows, FakeTokenizer(), self.recipe, self.issues,
                                     "train",
                                     require_families=self.manifest["rows"]["mask_families"])
        self.validation = TR.measure_rows(self.validation_rows, FakeTokenizer(),
                                          self.recipe, self.issues, "validation")
        self.assertTrue(self.issues.ok, self.issues.failures)
        self.identity = {
            "chat_template_sha256": self.recipe["tokenizer_chat_template_sha256"],
            "tokenizer_config_sha256": self.recipe["tokenizer_config_sha256"],
            "config_sha256": self.recipe["config_sha256"],
            "weights_sha256": self.recipe["weights_sha256"],
            "tokenizer_assets_sha256": self.recipe["tokenizer_assets_sha256"],
            "pad_token": PAD, "pad_token_id": 7, "eos_token": EOS,
            "commit": "a" * 40, "tokenizer_revision": "a" * 40}
        self.runtime = {"gpu": "A100", "python": "3.12", "torch": "2.9",
                        "transformers": "5.17", "trl": "1.0", "unsloth": "2026.10.5"}
        self.stops = [
            {"kind": "answer", "text": '[Ch. 1] "A watermark is a threshold."\nIt marks progress.<|im_end|>',
             "max_new_tokens_hit": False},
            {"kind": "refusal", "text": "Not in this book.<|im_end|>",
             "max_new_tokens_hit": False},
            {"kind": "history", "text": '[Ch. 3] "A later answer."\nIt follows.<|im_end|>',
             "max_new_tokens_hit": False}]

    def preflight(self):
        return TR.build_preflight_report(self.package(), self.recipe, self.train,
                                         self.validation, self.identity, self.stops,
                                         self.runtime)

    def test_run_report_passes_the_parent_gate(self):
        package = self.package()
        self.assertTrue(package.issues.ok, package.issues.failures)
        report = TR.build_run_report(
            package, self.recipe, self.train, self.validation, self.stops,
            self.runtime, [{"epoch": 1, "train": 1.0, "eval": 1.1}],
            {"lora_sha256": "a" * 64, "gguf_sha256": "b" * 64, "gguf_quant": "q4_k_m"},
            "c" * 64, "d" * 64, self.identity)
        issues = TR.new_issues()
        PT.verify_run(report, package.manifest, issues)
        TR.compare_package_facts(report["preflight"],
                                 TR.expected_package_facts(package), issues)
        self.assertTrue(issues.ok, issues.failures)

    def test_preflight_drift_is_refused(self):
        report = self.preflight()
        drifted = json.loads(json.dumps(self.train))
        drifted["assistant_label_tokens"] += 1
        issues = TR.new_issues()
        TR.compare_preflight(report, drifted, self.validation, self.identity, issues,
                             expected=TR.expected_package_facts(self.package()))
        self.assertIn("preflight_drift", {item["code"] for item in issues.failures})

    def test_tokenizer_asset_drift_is_refused(self):
        report = self.preflight()
        drifted = dict(self.identity)
        drifted["tokenizer_assets_sha256"] = {"tokenizer.json": "0" * 64,
                                              "special_tokens_map.json": "2" * 64}
        issues = TR.new_issues()
        TR.compare_preflight(report, self.train, self.validation, drifted, issues)
        self.assertIn("preflight_drift", {item["code"] for item in issues.failures})

    def test_run_report_requires_the_measured_tokenizer_assets(self):
        package = self.package()
        report = TR.build_run_report(
            package, self.recipe, self.train, self.validation, self.stops,
            self.runtime, [{"epoch": 1, "train": 1.0, "eval": 1.1}],
            {"lora_sha256": "a" * 64, "gguf_sha256": "b" * 64, "gguf_quant": "q4_k_m"},
            "c" * 64, "d" * 64, self.identity)
        report["preflight"]["tokenizer_assets_sha256"] = {}
        issues = TR.new_issues()
        PT.verify_run(report, package.manifest, issues)
        self.assertIn("run_preflight_incomplete",
                      {item["code"] for item in issues.failures})

    def test_preflight_data_hashes_are_enforced(self):
        package = self.package()
        report = self.preflight()
        report["dataset_sha256"] = "0" * 64
        report["validation_sha256"] = "1" * 64
        report["inventory_sha256"] = "2" * 64
        report_bytes = json.dumps(report).encode()
        issues = TR.new_issues()
        TR.verify_approval(self.approval(report_bytes), b"", report, report_bytes,
                           package, issues)
        codes = {item["code"] for item in issues.failures}
        self.assertIn("preflight_dataset_mismatch", codes)
        self.assertIn("preflight_validation_mismatch", codes)
        self.assertIn("preflight_inventory_mismatch", codes)
        drift = TR.new_issues()
        TR.compare_preflight(report, self.train, self.validation, self.identity, drift,
                             expected=TR.expected_package_facts(package))
        codes = {item["code"] for item in drift.failures}
        self.assertIn("preflight_dataset_mismatch", codes)
        self.assertIn("preflight_validation_mismatch", codes)
        self.assertIn("preflight_inventory_mismatch", codes)

    def test_approval_must_be_approved(self):
        report = self.preflight()
        report_bytes = json.dumps(report).encode()
        approval = self.approval(report_bytes)
        approval["decision"] = "rejected"
        issues = TR.new_issues()
        TR.verify_approval(approval, b"", report, report_bytes, self.package(), issues)
        self.assertIn("approval_not_approved", {item["code"] for item in issues.failures})

    def test_approval_must_bind_the_report_bytes(self):
        report = self.preflight()
        report_bytes = json.dumps(report).encode()
        approval = self.approval(b"other bytes")
        issues = TR.new_issues()
        TR.verify_approval(approval, b"", report, report_bytes, self.package(), issues)
        self.assertIn("approval_report_mismatch", {item["code"] for item in issues.failures})

    def test_approval_must_bind_the_export_recipe(self):
        report = self.preflight()
        report_bytes = json.dumps(report).encode()
        approval = self.approval(report_bytes)
        approval["export"] = {"gguf": "q8_0", "merged_16bit": False}
        issues = TR.new_issues()
        TR.verify_approval(approval, b"", report, report_bytes, self.package(), issues)
        self.assertIn("approval_export_mismatch", {item["code"] for item in issues.failures})

    def approval(self, report_bytes):
        package = self.package()
        return {"schema": TR.APPROVAL_SCHEMA, "decision": "approved",
                "reviewer": "reviewer-a", "approved_at": "2026-10-30T00:00:00Z",
                "manifest_sha256": package.manifest_sha256,
                "contract_sha256": package.contract_sha256,
                "preflight_report_sha256": PT.sha256_bytes(report_bytes),
                "export": package.contract["export"]}


class CliTests(Fixture):
    def test_help_does_not_need_the_gpu_stack(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(ROOT / "artifacts/colab/training_reviewed.py"), "--help"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("package", result.stdout)

    def test_import_does_not_pull_the_gpu_stack(self):
        import subprocess
        code = (
            "import sys; sys.path.insert(0, %r); import training_reviewed;"
            "print(','.join(m for m in ('torch','unsloth','trl','transformers','datasets')"
            " if m in sys.modules))" % str(ROOT / "artifacts/colab"))
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_package_cli_passes_a_good_fixture(self):
        out = self.tmp / "cli-good"
        code = TR.main(["package", "--manifest", str(self.manifest_path),
                        "--contract", str(self.contract_path), "--out", str(out)])
        self.assertEqual(code, 0)
        payload = json.loads((out / "package-check.json").read_text())
        self.assertEqual(payload["status"], "pass")

    def test_package_cli_refuses_a_blocked_manifest(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["status"] = "blocked"
        self.rewrite_manifest(manifest)
        out = self.tmp / "cli-blocked"
        with contextlib.redirect_stdout(io.StringIO()):
            code = TR.main(["package", "--manifest", str(self.manifest_path),
                            "--contract", str(self.contract_path), "--out", str(out)])
        self.assertEqual(code, 2)
        payload = json.loads((out / "package-check.json").read_text())
        self.assertEqual(payload["status"], "fail")
        self.assertIn("manifest_not_ready",
                      {failure["code"] for failure in payload["failures"]})

    def test_train_cli_refuses_before_gpu_and_keeps_a_failure_record(self):
        out = self.tmp / "cli-train-refused"
        with contextlib.redirect_stdout(io.StringIO()):
            code = TR.main(["train", "--manifest", str(self.manifest_path),
                            "--contract", str(self.contract_path),
                            "--preflight-report", str(self.tmp / "missing.json"),
                            "--approval", str(self.tmp / "missing-approval.json"),
                            "--out", str(out)])
        self.assertEqual(code, 2)
        payload = json.loads((out / "run-failure.json").read_text())
        self.assertEqual(payload["stage"], "train")
        self.assertIn("preflight_report_missing",
                      {failure["code"] for failure in payload["failures"]})

    def test_preflight_refuses_a_validated_fixture(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["status"] = "validated_fixture"
        self.rewrite_manifest(manifest)
        out = self.tmp / "cli-preflight-fixture"
        with contextlib.redirect_stdout(io.StringIO()):
            code = TR.main(["preflight", "--manifest", str(self.manifest_path),
                            "--contract", str(self.contract_path), "--out", str(out)])
        self.assertEqual(code, 2)
        payload = json.loads((out / "preflight-report.json").read_text())
        self.assertIn("manifest_not_ready",
                      {failure["code"] for failure in payload["failures"]})

    def test_preflight_cli_refuses_a_blocked_package(self):
        manifest = json.loads(json.dumps(self.manifest))
        manifest["status"] = "blocked"
        self.rewrite_manifest(manifest)
        out = self.tmp / "cli-preflight-blocked"
        with contextlib.redirect_stdout(io.StringIO()):
            code = TR.main(["preflight", "--manifest", str(self.manifest_path),
                            "--contract", str(self.contract_path), "--out", str(out)])
        self.assertEqual(code, 2)
        payload = json.loads((out / "preflight-report.json").read_text())
        self.assertEqual(payload["status"], "fail")
        self.assertIn("manifest_not_ready",
                      {failure["code"] for failure in payload["failures"]})


if __name__ == "__main__":
    unittest.main()


class ExportLayoutTests(unittest.TestCase):
    """Unsloth may write the GGUF to gguf_gguf; packaging must still find it."""

    class _Model:
        def __init__(self, layout):
            self.layout = layout

        def save_pretrained(self, path):
            Path(path).mkdir(parents=True, exist_ok=True)
            (Path(path) / "adapter_model.safetensors").write_bytes(b"adapter")

        def save_pretrained_merged(self, path, tokenizer, save_method=None):
            Path(path).mkdir(parents=True, exist_ok=True)
            (Path(path) / "model.safetensors").write_bytes(b"merged")

        def save_pretrained_gguf(self, path, tokenizer, quantization_method=None):
            target = Path(path) if self.layout == "gguf" else Path(path).parent / "gguf_gguf"
            target.mkdir(parents=True, exist_ok=True)
            (target / "model.Q4_K_M.gguf").write_bytes(b"gguf bytes")
            (target / "Modelfile").write_text("FROM ./model.Q4_K_M.gguf\n")

    def test_sibling_gguf_directory_is_packaged(self):
        tmp = Path(tempfile.mkdtemp(prefix="export-layout-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        facts = TR.export_artifacts(self._Model("gguf_gguf"),
                                    types.SimpleNamespace(save_pretrained=lambda path: None),
                                    tmp, "candidate")
        self.assertEqual(Path(facts["gguf_path"]).parent.name, "gguf_gguf")
        self.assertEqual(facts["gguf_bytes"], len(b"gguf bytes"))
        self.assertTrue(Path(facts["zip_path"]).is_file())
