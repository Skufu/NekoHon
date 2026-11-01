"""Small synthetic fixtures for the corpus-release verifier gate.

These tests do not read the multi-megabyte corpus artifacts. They build a
one-/two-row artifact directory in a temporary path, run the same public
validator/CLI a release reviewer uses, and mutate one factor at a time.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "artifacts" / "harnesses" / "corpus_release_verifier.py"
SPEC = importlib.util.spec_from_file_location("corpus_release_verifier", VERIFIER)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def messages(index):
    return [
        {"role": "system", "content": "Answer only from the passages."},
        {
            "role": "user",
            "content": (
                f"Question: q{index}?\n\nPassages:\n[Ch. 1] chunk_id=ch01-00{index}\n"
                f"Passage number {index} is a test sentence.\n\n"
                "Copy one sentence from a passage. Do not reword it.\n"
                'Format example, not an answer:\n[Ch. 2] "exact sentence copied from a passage"\n'
                "One short line in simple words."
            ),
        },
        {"role": "assistant", "content": "Not in this book."},
    ]


def build_fixture(root, rows=2, dev_support="dev:other"):
    root = Path(root)
    artifact = root / "artifact"
    candidate = artifact / "candidate-fixture"
    (root / "data").mkdir(parents=True, exist_ok=True)
    artifact.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(parents=True, exist_ok=True)
    original = root / "data" / "original.jsonl"
    original_lines = []
    for index in range(1, rows + 1):
        record = {"messages": messages(index), "meta": {"id": f"x3-line-{index:04d}"}}
        original_lines.append(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    original.write_text("".join(original_lines), encoding="utf-8")
    raw_lines = original.read_bytes().split(b"\n")[:-1]
    full_sha = sha_bytes(original.read_bytes())
    review_a = artifact / "review-a.jsonl"
    review_b = artifact / "review-b.jsonl"
    review_rows = [
        json.dumps(
            {
                "id": f"x3-line-{index:04d}",
                "review": {"status": "accepted", "reviewer": "fixture", "provenance": "agent", "criteria_version": "fixture"},
                "target_claims": [],
            },
            sort_keys=True,
        )
        for index in range(1, rows + 1)
    ]
    review_a.write_text("\n".join(review_rows) + "\n", encoding="utf-8")
    review_b.write_text("", encoding="utf-8")
    (artifact / "combined-review-check.json").write_text(
        json.dumps({"parts": [{"shard": "A", "sha256": sha_bytes(review_a.read_bytes())}, {"shard": "B", "sha256": sha_bytes(review_b.read_bytes())}]}),
        encoding="utf-8",
    )
    main_rows = []
    for index, record in enumerate((json.loads(line) for line in original_lines), 1):
        main_rows.append(
            {
                "id": f"x3-line-{index:04d}",
                "role": "historical_train",
                "line": index,
                "question": f"q{index}?",
                "target": {"kind": "refusal", "refusal_exact": True},
                "mechanical_status": "PASS",
                "messages_sha256": sha(json.dumps(record["messages"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
                "user_prompt_sha256": sha(record["messages"][1]["content"]),
                "target_sha256": sha(record["messages"][2]["content"]),
                "support_keys": ["dev:s" if dev_support else "fde:ch01-001"],
                "context_keys": [],
                "support_text_keys": [],
                "source_scope": [],
                "semantic_review": {
                    "shard": "A",
                    "review_ledger_path": str(review_a),
                    "decision": "accepted",
                    "binding_status": "BOUND",
                    "witnesses": {"total": 0, "valid": 0, "invalid": 0},
                },
            }
        )
    main_rows.append(
        {
            "id": "dev-row",
            "role": "dev",
            "line": 1,
            "question": "dev question?",
            "support_keys": [dev_support] if dev_support else [],
            "context_keys": [],
            "support_text_keys": [],
        }
    )
    (artifact / "ledger.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in main_rows) + "\n", encoding="utf-8")
    candidate_rows = []
    proposal = []
    for index, record in enumerate((json.loads(line) for line in original_lines), 1):
        candidate_rows.append(
            {
                "id": f"x3-line-{index:04d}",
                "selected": True,
                "fold": "validation",
                "origin": {"path": str(original), "sha256": full_sha, "record": str(index), "line_sha256": sha_bytes(raw_lines[index - 1])},
                "semantic_decision": "accepted",
                "semantic_binding_status": "BOUND",
                "mechanical_status": "PASS",
                "messages_sha256": sha(json.dumps(record["messages"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
                "target_sha256": sha(record["messages"][2]["content"]),
                "target_kind": "refusal",
                "original_issue_codes": [],
                "support_keys": ["dev:s" if dev_support else "fde:ch01-001"],
                "context_keys": [],
                "support_text_keys": [],
                "full_component_id": "component-1",
                "candidate_component_id": "candidate-1",
            }
        )
        proposal.append(record)
    (candidate / "candidate-ledger.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in candidate_rows) + "\n", encoding="utf-8")
    (candidate / "candidate-proposal.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in proposal) + "\n", encoding="utf-8")
    manifest = {
        "status": "PROVISIONAL_REVIEWED_INPUTS_NOT_CERTIFIED",
        "ready_for_training": False,
        "prospective_eligible": True,
        "launchable": False,
        "canonical_bind_pending": True,
        "certified_gpu_release": False,
        "counts": {"selected": rows, "train": 0, "validation": rows},
        "checks": {"zero_target_support_straddle": True, "support_key_cross_fold": [], "support_text_cross_fold": [], "question_cross_fold": [], "duplicate_input_cross_fold": [], "full_component_cross_fold": [], "candidate_component_cross_fold": [], "dev_question_overlap": []},
        "coverage": {"target_kinds": {"refusal": rows}, "refusals": rows, "synthetic_rows": 0},
        "artifacts": {
            "candidate_proposal_sha256": sha_bytes((candidate / "candidate-proposal.jsonl").read_bytes()),
            "candidate_ledger_sha256": sha_bytes((candidate / "candidate-ledger.jsonl").read_bytes()),
        },
    }
    (candidate / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact, candidate


class CorpusVerifierTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_good_fixture_passes(self):
        artifact, _ = build_fixture(self.root)
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "PASS", report["reasons"])
        self.assertEqual(report["counts"]["proposal"], 2)

    def test_truncated_proposal_fails(self):
        artifact, candidate = build_fixture(self.root)
        proposal = candidate / "candidate-proposal.jsonl"
        lines = proposal.read_text(encoding="utf-8").splitlines()
        proposal.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("proposal_length", {reason["code"] for reason in report["reasons"]})

    def test_changed_review_pin_fails(self):
        artifact, _ = build_fixture(self.root)
        combined = json.loads((artifact / "combined-review-check.json").read_text(encoding="utf-8"))
        combined["parts"][0]["sha256"] = "0" * 64
        (artifact / "combined-review-check.json").write_text(json.dumps(combined), encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("review_pins", {reason["code"] for reason in report["reasons"]})

    def test_mixed_full_component_folds_fails(self):
        artifact, candidate = build_fixture(self.root)
        ledger_path = candidate / "candidate-ledger.jsonl"
        rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
        rows[1]["fold"] = "train"
        ledger_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
        manifest_path = candidate / "candidate-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["candidate_ledger_sha256"] = sha_bytes(ledger_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("full_component_mixed_fold", {reason["code"] for reason in report["reasons"]})

    def test_dev_support_overlap_fails(self):
        artifact, _ = build_fixture(self.root, dev_support="dev:s")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("dev_support_overlap", {reason["code"] for reason in report["reasons"]})

    def _rewrite_candidate_ledger(self, candidate, mutate):
        path = candidate / "candidate-ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        mutate(rows[0])
        path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
        manifest_path = candidate / "candidate-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["candidate_ledger_sha256"] = sha_bytes(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _rewrite_mechanical_both(self, artifact, candidate, status):
        candidate_path = candidate / "candidate-ledger.jsonl"
        candidate_rows = [json.loads(line) for line in candidate_path.read_text(encoding="utf-8").splitlines()]
        candidate_rows[0]["mechanical_status"] = status
        candidate_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in candidate_rows) + "\n", encoding="utf-8")
        main_path = artifact / "ledger.jsonl"
        main_rows = [json.loads(line) for line in main_path.read_text(encoding="utf-8").splitlines()]
        main_rows[0]["mechanical_status"] = status
        main_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in main_rows) + "\n", encoding="utf-8")
        manifest_path = candidate / "candidate-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["candidate_ledger_sha256"] = sha_bytes(candidate_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_selected_status_mutants_fail(self):
        for field, value in (("semantic_decision", "needs_review"), ("semantic_binding_status", "INVALID"), ("mechanical_status", "FAIL")):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp:
                    artifact, candidate = build_fixture(temp)
                    self._rewrite_candidate_ledger(candidate, lambda row, f=field, v=value: row.__setitem__(f, v))
                    report = V.validate(artifact, root=Path(temp))
                    self.assertEqual(report["status"], "FAIL")
                    self.assertIn("selected_status", {reason["code"] for reason in report["reasons"]})
        with self.subTest(field="mechanical_status", value="UNKNOWN_both"):
            with tempfile.TemporaryDirectory() as temp:
                artifact, candidate = build_fixture(temp)
                self._rewrite_mechanical_both(artifact, candidate, "UNKNOWN")
                report = V.validate(artifact, root=Path(temp))
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("selected_status", {reason["code"] for reason in report["reasons"]})

    def test_public_cli_rejects_rehashed_status_mutant(self):
        artifact, candidate = build_fixture(self.root)
        self._rewrite_candidate_ledger(candidate, lambda row: row.__setitem__("semantic_binding_status", "INVALID"))
        with contextlib.redirect_stdout(io.StringIO()):
            code = V.main(["--artifactdir", str(artifact), "--root", str(self.root)])
        self.assertEqual(code, 1)

    def test_reviewed_mechanical_warning_is_allowed(self):
        artifact, candidate = build_fixture(self.root)
        path = candidate / "candidate-ledger.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["mechanical_status"] = "REVIEW"
        rows[0]["original_issue_codes"] = ["refusal_with_context_terms"]
        path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
        main_path = artifact / "ledger.jsonl"
        main_rows = [json.loads(line) for line in main_path.read_text(encoding="utf-8").splitlines()]
        main_rows[0]["mechanical_status"] = "REVIEW"
        main_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in main_rows) + "\n", encoding="utf-8")
        manifest_path = candidate / "candidate-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artifacts"]["candidate_ledger_sha256"] = sha_bytes(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "PASS", report["reasons"])

    def test_stale_candidate_manifest_sidecar_fails(self):
        artifact, candidate = build_fixture(self.root)
        manifest_path = candidate / "candidate-manifest.json"
        sidecar = candidate / "candidate-manifest.sha256"
        sidecar.write_text(sha_bytes(manifest_path.read_bytes()) + "\n", encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["seed"] = 999
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("sidecars", {reason["code"] for reason in report["reasons"]})

    def test_readiness_contradiction_fails_but_ready_false_passes(self):
        artifact, candidate = build_fixture(self.root)
        manifest_path = candidate / "candidate-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["launchable"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = V.validate(artifact, root=self.root)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("readiness_consistency", {reason["code"] for reason in report["reasons"]})


if __name__ == "__main__":
    unittest.main()
