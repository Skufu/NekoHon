"""The offline freeze checker must compare distribution names, not spellings.

Why this test exists: the one authorized Colab attempt failed before training
because `check_runtime_freeze.py` keyed lock names and `pip freeze` names by
lowercase only. Seven distributions are spelled with `_` by `pip freeze` and
with `-` in `requirements-locked.txt`, so the saved run recorded seven
missing packages that were installed at the locked versions. The versions
were never wrong; only the names differed.

Rules asserted here:

1. The actual saved `runtime-freeze.json`/`runtime-freeze.txt` and the frozen
   103-pin lock pass the repaired checker, byte for byte.
2. The frozen checker, run on those same bytes, still reports exactly those
   seven false misses. This test is the regression witness, not a fixture.
3. Mutating one version, removing one package, or removing the lock still
   fails. Name normalization must not relax version comparison.
4. `-`, `_`, `.` and case are equivalent for names only, and a canonical name
   carrying two different versions fails rather than one silently winning.
5. The CLI is exercised as a subprocess in a temporary copy of the upload
   layout, with no monkeypatching, and keeps the existing report shape and
   `--manifest` override.

The capture and lock live under gitignored `artifacts/runs/`; the saved-bytes
tests skip on a machine without them. The synthetic tests need only the
repaired checker that ships with the repo.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED = ROOT / "artifacts" / "colab" / "check_runtime_freeze.py"
RELEASE = ROOT / "artifacts" / "runs" / "data-release-2026-10-29" / "colab"
CAPTURE = RELEASE / "attempt-1" / "preflight"
FROZEN = (RELEASE / "launch-packet-fixed" / "closure" / "artifacts" / "colab"
          / "check_runtime_freeze.py")
LOCK = RELEASE / "launch-packet-fixed" / "closure" / "artifacts" / "colab" / "requirements-locked.txt"
MANIFEST = RELEASE / "launch-packet-fixed" / "closure" / "release-manifest.json"

REPORT_SHA256 = "4e0aaea93e0092d23222f06c3ce545a4ce75cd3d1ee0e2cbbb61a4690323c519"
FREEZE_SHA256 = "2d32a0923a78ac5d7ff530f944932c50241e2c4315c8157a490603753325498f"
LOCK_SHA256 = "3057ee4e20c84b23fd65175fd4950b8ac2c4969cf2d790666b491c445dcce01b"
FROZEN_SHA256 = "37cf563e4734bdb98a9dc679d80d9a670c8a067ebbcd1edb560c2d9691601269"
CAPTURED = all(path.exists() for path in (
    CAPTURE / "runtime-freeze.json", CAPTURE / "runtime-freeze.txt",
    FROZEN, LOCK, MANIFEST))

FALSE_MISSES = [
    "docstring-parser locked 0.18.0, installed None",
    "hf-transfer locked 0.1.9, installed None",
    "huggingface-hub locked 1.33.0, installed None",
    "importlib-metadata locked 10.1.0, installed None",
    "pydantic-core locked 2.50.2, installed None",
    "typing-extensions locked 4.16.0, installed None",
    "unsloth-zoo locked 2026.10.10, installed None",
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(name):
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def parse_pins(text):
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==", 1)
            pins[canonical(name)] = version.strip()
    return pins


class RuntimeFreezeRepairTest(unittest.TestCase):
    def run_cli(self, root, report="artifacts/colab/runtime-freeze.json",
                manifest="release-manifest.json"):
        proc = subprocess.run(
            [sys.executable, str(root / "artifacts" / "colab" / "check_runtime_freeze.py"),
             report, "--manifest", manifest],
            cwd=root, capture_output=True, text=True)
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc, payload

    def stage(self, root, checker):
        colab = root / "artifacts" / "colab"
        colab.mkdir(parents=True)
        shutil.copyfile(checker, colab / "check_runtime_freeze.py")
        shutil.copyfile(LOCK, colab / "requirements-locked.txt")
        shutil.copyfile(CAPTURE / "runtime-freeze.json", colab / "runtime-freeze.json")
        shutil.copyfile(CAPTURE / "runtime-freeze.txt", colab / "runtime-freeze.txt")
        shutil.copyfile(MANIFEST, root / "release-manifest.json")
        return colab

    def stage_synthetic(self, root, lock_text, freeze_text, expected=None):
        colab = root / "artifacts" / "colab"
        colab.mkdir(parents=True)
        shutil.copyfile(FIXED, colab / "check_runtime_freeze.py")
        (colab / "requirements-locked.txt").write_text(lock_text, encoding="utf-8")
        (colab / "runtime-freeze.txt").write_text(freeze_text, encoding="utf-8")
        (colab / "runtime-freeze.json").write_text(json.dumps({
            "schema": "runtime-freeze/1", "python": "3.13.16", "versions": {}}),
            encoding="utf-8")
        (root / "release-manifest.json").write_text(json.dumps({
            "dependencies": {"expected_top_level": expected or {"python": "recorded"}}}),
            encoding="utf-8")

    @unittest.skipUnless(CAPTURED, "saved data-release capture is not on this machine")
    def test_captured_bytes_pass_full_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            colab = self.stage(root, FIXED)
            self.assertEqual(sha256(colab / "runtime-freeze.json"), REPORT_SHA256)
            self.assertEqual(sha256(colab / "runtime-freeze.txt"), FREEZE_SHA256)
            self.assertEqual(sha256(colab / "requirements-locked.txt"), LOCK_SHA256)
            locked = parse_pins((colab / "requirements-locked.txt").read_text(encoding="utf-8"))
            installed = parse_pins((colab / "runtime-freeze.txt").read_text(encoding="utf-8"))
            self.assertEqual(len(locked), 103)
            self.assertEqual({name: installed.get(name) for name in locked}, locked)

            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["failures"], [])
        self.assertEqual(set(payload), {"status", "failures", "expected", "observed"})
        self.assertEqual(payload["expected"], {
            "peft": "recorded", "python": "recorded", "torch": "recorded",
            "transformers": "5.17.0", "trl": "recorded", "unsloth": "2026.10.5"})
        self.assertEqual(payload["observed"]["python"], "3.13.16")

    @unittest.skipUnless(CAPTURED, "saved data-release capture is not on this machine")
    def test_frozen_checker_reports_seven_false_misses(self):
        self.assertEqual(sha256(FROZEN), FROZEN_SHA256)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage(root, FROZEN)
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["failures"], FALSE_MISSES)

    @unittest.skipUnless(CAPTURED, "saved data-release capture is not on this machine")
    def test_one_wrong_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            colab = self.stage(root, FIXED)
            text = (colab / "runtime-freeze.txt").read_text(encoding="utf-8")
            (colab / "runtime-freeze.txt").write_text(
                text.replace("pydantic_core==2.50.2", "pydantic_core==2.50.3"),
                encoding="utf-8")
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertIn("pydantic-core locked 2.50.2, installed '2.50.3'", payload["failures"])

    @unittest.skipUnless(CAPTURED, "saved data-release capture is not on this machine")
    def test_one_missing_package_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            colab = self.stage(root, FIXED)
            text = (colab / "runtime-freeze.txt").read_text(encoding="utf-8")
            (colab / "runtime-freeze.txt").write_text(
                text.replace("typing_extensions==4.16.0\n", ""), encoding="utf-8")
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertIn("typing-extensions locked 4.16.0, installed None", payload["failures"])

    @unittest.skipUnless(CAPTURED, "saved data-release capture is not on this machine")
    def test_missing_lock_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            colab = self.stage(root, FIXED)
            (colab / "requirements-locked.txt").unlink()
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertIn("requirements-locked.txt is missing; refusing a top-level-only check",
                      payload["failures"])

    def test_name_separators_and_case_are_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage_synthetic(
                root,
                "Foo.Bar_Baz==1.2.3\nQUX-quux==4.5.6\n",
                "foo-bar-baz==1.2.3\nqux_QUUX==4.5.6\n")
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(payload["failures"], [])

    def test_duplicate_conflicting_versions_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage_synthetic(
                root,
                "typing-extensions==4.16.0\n",
                "typing_extensions==4.16.0\ntyping-extensions==4.15.0\n")
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertIn("runtime-freeze.txt lists typing-extensions twice with different versions",
                      " ".join(payload["failures"]))

    def test_duplicate_same_version_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage_synthetic(
                root,
                "typing-extensions==4.16.0\n",
                "typing_extensions==4.16.0\ntyping-extensions==4.16.0\n")
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(payload["failures"], [])

    def test_manifest_override_and_recorded_semantics_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.stage_synthetic(root, "peft==0.21.2\n", "peft==0.21.2\n",
                                 expected={"peft": "recorded"})
            proc, payload = self.run_cli(root)

        self.assertEqual(proc.returncode, 2)
        self.assertEqual(payload["failures"], ["peft not recorded"])


if __name__ == "__main__":
    unittest.main()
