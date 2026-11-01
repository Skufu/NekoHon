"""Behaviour tests for the one-attempt OS-background reviewed-job driver.

The driver is exercised as a real subprocess so heartbeat, atomic status,
approval waiting, and terminal state are observed from outside. The stage
commands are small synthetic scripts; no Colab, model, network, or GPU is used.
The fixture runner implements the same approval API the real runner exposes;
a separate test calls the real ``training_reviewed.verify_approval``.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "colab"))

import training_reviewed as TR  # noqa: E402
import watch_training as WT  # noqa: E402

DRIVER = ROOT / "artifacts" / "colab" / "run_reviewed_job.py"
PY = sys.executable


def sha_file(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_status(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def wait_status(path, predicate, timeout=15.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if Path(path).is_file():
            try:
                last = read_status(path)
            except Exception:
                last = None
            if last is not None and predicate(last):
                return last
        time.sleep(0.02)
    raise AssertionError("status predicate not met; last=%r" % (last,))


FIXTURE_RUNNER = r'''
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


class Issues:
    def __init__(self):
        self.failures = []

    @property
    def ok(self):
        return not self.failures

    def fail(self, code, detail):
        self.failures.append({"code": code, "detail": detail})


def new_issues():
    return Issues()


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_package(manifest, contract, **kwargs):
    m = json.loads(Path(manifest).read_text())
    c = json.loads(Path(contract).read_text())
    return SimpleNamespace(
        manifest=m, contract=c,
        manifest_sha256=_sha_file(manifest), contract_sha256=_sha_file(contract),
        validation_block={}, issues=new_issues(),
        facts={"controls_sha256": "controls",
               "inventory": {"sha256": "inventory", "fragment_sha256": "fragment",
                             "receipt_sha256": "receipt"}},
    )


def verify_approval(approval, approval_bytes, report, report_bytes, package, issues):
    if approval.get("schema") != "training-preflight-approval/1":
        issues.fail("schema", "wrong approval schema")
    if str(approval.get("decision", "")).lower() != "approved":
        issues.fail("decision", "not approved")
    if not approval.get("reviewer") or not approval.get("approved_at"):
        issues.fail("attribution", "reviewer and approved_at required")
    if approval.get("manifest_sha256") != package.manifest_sha256:
        issues.fail("manifest", "manifest mismatch")
    if approval.get("contract_sha256") != package.contract_sha256:
        issues.fail("contract", "contract mismatch")
    if approval.get("preflight_report_sha256") != hashlib.sha256(report_bytes).hexdigest():
        issues.fail("report", "report mismatch")
    if report.get("status") != "pass":
        issues.fail("report_status", "report is not passing")
    if approval.get("export") != package.contract.get("export"):
        issues.fail("export", "export mismatch")
'''


STAGE = r'''
import json
import sys
import time
import zipfile
from pathlib import Path


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")


mode = sys.argv[1]
if mode == "freeze":
    write(sys.argv[2], {"schema": "runtime-freeze/1", "versions": {"torch": "test"}})
    Path(sys.argv[3]).write_text("torch==test\n")
elif mode == "guard":
    Path(sys.argv[2]).write_text("guard-ran\n")
elif mode == "gate":
    write(sys.argv[2], {"status": "ready-to-launch", "inputs": {}})
elif mode == "derive":
    write(sys.argv[2], {"export": {"gguf": "q4_k_m", "merged_16bit": True}})
elif mode == "package":
    code = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    write(sys.argv[2], {"status": "pass" if code == 0 else "fail"})
    sys.exit(code)
elif mode == "preflight":
    report, code, manifest, contract = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
    sleep = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
    if sleep:
        time.sleep(sleep)
    write(report, {"schema": "training-preflight-report/1", "status": "pass",
                   "manifest_sha256": manifest, "contract_sha256": contract})
    sys.exit(code)
elif mode == "preflight_fail":
    out = Path(sys.argv[2])
    code = int(sys.argv[3])
    write(out / "preflight-failure.json",
          {"schema": "training-preflight-failure/1", "stage": "preflight",
           "status": "fail",
           "failures": [{"code": "base_revision_unresolved",
                         "detail": "synthetic identity gap"}],
           "notes": ["synthetic runner failure"]})
    write(out / "identity-measurement.json",
          {"schema": "training-identity-measurement/1",
           "base_model": "fixture/model",
           "config_sha256": "c" * 64,
           "loader_commit_hash": None,
           "weights": {"model.safetensors": "d" * 64}})
    (out / "events.jsonl").write_text(
        '{"event": "model_loaded"}\n{"event": "preflight_failed"}\n')
    sys.exit(code)
elif mode == "preflight_bare_fail":
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    sys.exit(int(sys.argv[3]))
elif mode == "preflight_ok_no_report":
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    sys.exit(0)
elif mode == "train":
    out = Path(sys.argv[2])
    counter = Path(sys.argv[3])
    report = Path(sys.argv[4])
    code = int(sys.argv[5])
    sleep = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
    counter.parent.mkdir(parents=True, exist_ok=True)
    with counter.open("a") as handle:
        handle.write("call\n")
    checkpoint = out / "checkpoints" / "checkpoint-1"
    checkpoint.mkdir(parents=True, exist_ok=True)
    (checkpoint / "adapter_model.safetensors").write_bytes(b"checkpoint" * 40)
    (out / "events.jsonl").write_text('{"event": "train_start"}\n')
    if sleep:
        time.sleep(sleep)
    if code == 0:
        (out / "lora").mkdir(parents=True, exist_ok=True)
        (out / "lora" / "adapter_model.safetensors").write_bytes(b"adapter" * 60)
        (out / "merged_16bit").mkdir(parents=True, exist_ok=True)
        (out / "merged_16bit" / "config.json").write_text("{}\n")
        (out / "gguf").mkdir(parents=True, exist_ok=True)
        gguf = out / "gguf" / "model.q4_k_m.gguf"
        gguf.write_bytes(b"gguf" * 300)
        with zipfile.ZipFile(out / "model_q4_k_m.zip", "w") as archive:
            archive.write(gguf, gguf.name)
        write(report, {"schema": "training-run-report/1", "status": "pass"})
        with (out / "events.jsonl").open("a") as handle:
            handle.write('{"event": "train_end"}\n')
    else:
        write(out / "run-failure.json",
              {"schema": "training-run-failure/1", "stage": "train",
               "status": "fail", "error": "synthetic train failure",
               "notes": ["checkpoint survives"]})
        write(out / "identity-measurement.json",
              {"schema": "training-identity-measurement/1",
               "base_model": "fixture/model", "loader_commit_hash": None})
    sys.exit(code)
'''


INSTALL = r'''
import sys
import time
from pathlib import Path
marker = Path(sys.argv[1])
if len(sys.argv) > 2:
    time.sleep(float(sys.argv[2]))
marker.parent.mkdir(parents=True, exist_ok=True)
marker.write_text("installed\n")
'''


def build_plan(tmp, *, package_exit=0, preflight_exit=0, train_exit=0, train_sleep=0.0,
               preflight_sleep=0.0, chunk_size=4096, lock_pins=3,
               generated_package=False, with_stages=False, preflight_mode="preflight"):
    tmp = Path(tmp)
    work = tmp / "work"
    out = tmp / "out"
    job = tmp / "job"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    job.mkdir(parents=True, exist_ok=True)

    runner = write(tmp / "runner_fixture.py", FIXTURE_RUNNER)
    install = write(tmp / "install.py", INSTALL)
    deps = write(tmp / "requirements-locked.txt", "a==1\nb==2\nc==3\n")
    manifest_path = tmp / "manifest.json"
    contract_path = tmp / "contract.json"
    if generated_package:
        manifest_path = work / "gate-out" / "manifest.json"
        contract_path = work / "training-runner-contract.json"
    else:
        write(manifest_path, json.dumps({"status": "ready-to-launch"}))
        write(contract_path, json.dumps({"export": {"gguf": "q4_k_m", "merged_16bit": True}}))
    spec = write(tmp / "gate-spec.json", json.dumps({"status": "certified"}))
    contract_source = write(tmp / "contract-source.json",
                            json.dumps({"export": {"gguf": "q4_k_m", "merged_16bit": True}}))
    stage = write(tmp / "stage.py", STAGE)

    paths = {
        "package_check": work / "package-check.json",
        "preflight_report": work / "preflight-report.json",
        "runtime_freeze_json": work / "runtime-freeze.json",
        "runtime_freeze_txt": work / "runtime-freeze.txt",
        "run_report": out / "training-run-report.json",
        "events": out / "events.jsonl",
        "failure": work / "failure.json",
        "download_manifest": work / "download-manifest.json",
        "lora_dir": out / "lora",
        "merged_dir": out / "merged_16bit",
        "checkpoints_dir": out / "checkpoints",
        "gguf_zip": out / "model_q4_k_m.zip",
        "approval": work / "approval.json",
    }
    if preflight_mode == "preflight":
        preflight_command = [PY, str(stage), "preflight",
                             str(paths["preflight_report"]), str(preflight_exit),
                             sha_file(manifest_path) if manifest_path.exists() else "generated",
                             sha_file(contract_path) if contract_path.exists() else "generated",
                             str(preflight_sleep)]
    else:
        preflight_command = [PY, str(stage), preflight_mode,
                             str(paths["preflight_report"].parent), str(preflight_exit)]
    plan = {
        "schema": "reviewed-job-plan/1",
        "job_uuid": "job-test-0001",
        "session": "test-session",
        "source_hash": sha_file(DRIVER),
        "package_hash": sha_bytes(b"approved-package-archive"),
        "job_dir": str(job),
        "status_path": str(job / "status.json"),
        "log_path": str(job / "job.log"),
        "heartbeat_seconds": 0.05,
        "approval_poll_seconds": 0.01,
        "chunk_size_bytes": chunk_size,
        "sources": {
            "runner": {"path": str(runner), "sha256": sha_file(runner)},
            "install": {"path": str(install), "sha256": sha_file(install)},
            "deps": {"path": str(deps), "sha256": sha_file(deps)},
        },
        "package": {
            "manifest": ({"path": str(manifest_path), "generated": True}
                         if generated_package else
                         {"path": str(manifest_path), "sha256": sha_file(manifest_path)}),
            "contract": ({"path": str(contract_path), "generated": True}
                         if generated_package else
                         {"path": str(contract_path), "sha256": sha_file(contract_path)}),
            "spec": {"path": str(spec), "sha256": sha_file(spec)},
            "contract_source": {"path": str(contract_source),
                                "sha256": sha_file(contract_source)},
            "lock": {"path": str(deps), "sha256": sha_file(deps)},
            "lock_pins": lock_pins,
        },
        "commands": {
            "install": [PY, str(install), str(tmp / "install-ran")],
            "freeze": [[PY, str(stage), "freeze", str(paths["runtime_freeze_json"]),
                        str(paths["runtime_freeze_txt"])]],
            "package": [PY, str(stage), "package", str(paths["package_check"]), str(package_exit)],
            "preflight": preflight_command,
            "train": [PY, str(stage), "train", str(out), str(tmp / "train-count"),
                      str(paths["run_report"]), str(train_exit), str(train_sleep),
                      "--manifest", str(manifest_path), "--contract", str(contract_path),
                      "--preflight-report", str(paths["preflight_report"]),
                      "--approval", str(paths["approval"])],
        },
        "paths": {key: str(value) for key, value in paths.items()},
    }
    if with_stages:
        plan["commands"]["guard"] = [PY, str(stage), "guard", str(tmp / "guard-ran")]
        plan["commands"]["gate"] = [PY, str(stage), "gate", str(manifest_path)]
        plan["commands"]["derive_contract"] = [PY, str(stage), "derive", str(contract_path)]
    plan_path = write(tmp / "plan.json", json.dumps(plan, indent=1, sort_keys=True))
    return plan, plan_path


def write_approval(plan, status, export=None):
    approval = {
        "schema": "training-preflight-approval/1",
        "decision": "approved",
        "reviewer": "independent-test",
        "approved_at": "2026-10-30T00:00:00Z",
        "manifest_sha256": sha_file(plan["package"]["manifest"]["path"]),
        "contract_sha256": sha_file(plan["package"]["contract"]["path"]),
        "preflight_report_sha256": status["preflight_report_sha256"],
        "export": export or json.loads(Path(plan["package"]["contract"]["path"]).read_text())["export"],
    }
    write(plan["paths"]["approval"], json.dumps(approval, indent=1, sort_keys=True))
    return approval


def driver_argv(plan_path, extra=()):
    return [PY, str(DRIVER), "--plan", str(plan_path),
            "--plan-sha256", sha_file(plan_path), *extra]


def start(plan_path):
    return subprocess.Popen(driver_argv(plan_path),
                            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)


def finish(proc, timeout=15.0):
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise AssertionError("driver did not finish; stdout=%r stderr=%r" % (out, err))
    return proc.returncode, out, err


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reviewed-job-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_plan_and_changed_source_blocks_before_launch(self):
        plan, plan_path = build_plan(self.tmp)
        check = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                               cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(json.loads(check.stdout)["status"], "pass")
        with Path(plan["sources"]["install"]["path"]).open("a") as handle:
            handle.write("\n# changed\n")
        proc = subprocess.run(driver_argv(plan_path),
                              cwd=str(ROOT), capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(Path(self.tmp / "install-ran").exists())
        self.assertFalse(Path(plan["status_path"]).exists())

    def test_plan_hash_binding_blocks_changed_stage_argv(self):
        plan, plan_path = build_plan(self.tmp)
        trusted = sha_file(plan_path)
        raw = json.loads(Path(plan_path).read_text())
        raw["commands"]["install"] = [PY, "-c", "open('changed', 'w').write('ran')"]
        Path(plan_path).write_text(json.dumps(raw))
        proc = subprocess.run([PY, str(DRIVER), "--plan", str(plan_path),
                               "--plan-sha256", trusted],
                              cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["status"], "plan_hash_mismatch")
        self.assertFalse(Path(self.tmp / "changed").exists())
        self.assertFalse(Path(plan["status_path"]).exists())

    def test_plan_requires_64_hex_identity_and_exact_session(self):
        plan, plan_path = build_plan(self.tmp)
        raw = json.loads(Path(plan_path).read_text())
        raw["package_hash"] = "not-a-hash"
        Path(plan_path).write_text(json.dumps(raw))
        bad = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                             cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        raw["package_hash"] = plan["package_hash"]
        raw["session"] = ""
        Path(plan_path).write_text(json.dumps(raw))
        bad = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                             cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)

    def test_detached_status_is_readable_and_heartbeats(self):
        plan, plan_path = build_plan(self.tmp, preflight_exit=1, preflight_sleep=0.7)
        proc = start(plan_path)
        try:
            first = wait_status(plan["status_path"],
                                lambda s: s.get("state") == "preflight")
            required = {"job_uuid", "session", "source_hash", "package_hash", "pid",
                        "state", "heartbeat_at", "log_path"}
            self.assertTrue(required.issubset(first))
            self.assertEqual(first["session"], "test-session")
            self.assertEqual(first["source_hash"], sha_file(DRIVER))
            self.assertEqual(first["package_hash"], plan["package_hash"])
            os.kill(first["pid"], 0)
            time.sleep(0.2)
            second = read_status(plan["status_path"])
            self.assertGreater(second["heartbeat_at"], first["heartbeat_at"])
        finally:
            code, out, err = finish(proc)
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(read_status(plan["status_path"])["state"], "failed")

    def test_preflight_failure_never_trains(self):
        plan, plan_path = build_plan(self.tmp, preflight_exit=1)
        code, out, err = finish(start(plan_path))
        self.assertEqual(code, 1, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "failed")
        self.assertNotEqual(status["child_exit_code"], 0)
        self.assertTrue(Path(status["failure_path"]).is_file())
        self.assertFalse(Path(self.tmp / "train-count").exists())
        self.assertTrue(Path(self.tmp / "install-ran").is_file())

    def test_package_check_failure_blocks_before_preflight_and_train(self):
        plan, plan_path = build_plan(self.tmp, package_exit=1)
        code, out, err = finish(start(plan_path))
        self.assertEqual(code, 1, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "failed")
        self.assertFalse(Path(plan["paths"]["preflight_report"]).exists())
        self.assertFalse(Path(self.tmp / "train-count").exists())

    def test_awaiting_approval_handoff_then_train_once_and_complete(self):
        plan, plan_path = build_plan(self.tmp)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            self.assertEqual(awaiting["state"], "preflight")
            names = {Path(path).name for path in awaiting["report_paths"]}
            self.assertTrue({"preflight-report.json", "runtime-freeze.json",
                             "runtime-freeze.txt"}.issubset(names))
            for path in awaiting["report_paths"]:
                self.assertEqual(awaiting["artifact_hashes"][path], sha_file(path))
            snapshot = awaiting["log_snapshot_path"]
            self.assertEqual(awaiting["artifact_hashes"][snapshot], sha_file(snapshot))
            self.assertEqual(awaiting["log_snapshot_sha256"], sha_file(snapshot))
            self.assertNotIn(awaiting["log_path"], awaiting["artifact_hashes"])
            self.assertEqual(awaiting["log_artifact_paths"], [snapshot])
            handoff_kinds = {item["kind"] for item in awaiting["artifacts"]}
            self.assertEqual(handoff_kinds, {"report", "log"})
            self.assertEqual(len({item["local_name"] for item in awaiting["artifacts"]}),
                             len(awaiting["artifacts"]))
            self.assertFalse(Path(self.tmp / "train-count").exists())
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["child_exit_code"], 0)
        self.assertTrue(status["artifacts_complete"])
        self.assertEqual(len(Path(self.tmp / "train-count").read_text().splitlines()), 1)
        for item in status["artifacts"]:
            self.assertEqual(item["sha256"], sha_file(item["path"]))
            self.assertEqual(item["role"], item["kind"])
            self.assertFalse(Path(item["local_name"]).is_absolute())
            self.assertEqual(Path(item["local_name"]).name, item["local_name"])
        self.assertEqual(len({item["local_name"] for item in status["artifacts"]}),
                         len(status["artifacts"]))
        kinds = {item["kind"] for item in status["artifacts"]}
        self.assertEqual(kinds, {"model", "report", "log"})
        model_formats = {item["format"] for item in status["artifacts"]
                         if item["kind"] == "model"}
        self.assertEqual(model_formats, {"gguf", "safetensors"})
        for kind in ("report", "log"):
            self.assertTrue(any(item["kind"] == kind for item in status["artifacts"]))
            self.assertTrue(any(item["sha256"] for item in status["artifacts"]
                                if item["kind"] == kind))
        self.assertNotIn(status["log_path"], status["report_paths"])
        self.assertTrue(status["log_artifact_paths"])
        for path in status["log_artifact_paths"]:
            self.assertIn(path, status["artifact_hashes"])
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["missing"], [])
        names = {item["name"] for item in manifest["artifacts"]}
        self.assertTrue({"lora.zip", "merged_16bit.zip", "gguf.zip"}.issubset(names))

    def test_final_stage_shape_generates_contract_then_trains(self):
        plan, plan_path = build_plan(self.tmp, generated_package=True, with_stages=True)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            self.assertTrue(Path(self.tmp / "guard-ran").is_file())
            self.assertTrue(Path(plan["package"]["manifest"]["path"]).is_file())
            self.assertTrue(Path(plan["package"]["contract"]["path"]).is_file())
            self.assertEqual(awaiting["generated_manifest_sha256"],
                             sha_file(plan["package"]["manifest"]["path"]))
            self.assertEqual(awaiting["generated_contract_sha256"],
                             sha_file(plan["package"]["contract"]["path"]))
            self.assertTrue(Path(plan["paths"]["package_check"]).is_file())
            self.assertTrue(Path(self.tmp / "install-ran").is_file())
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(read_status(plan["status_path"])["state"], "complete")

    def test_invalid_approval_blocks_train(self):
        plan, plan_path = build_plan(self.tmp)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting, export={"gguf": "q8_0", "merged_16bit": True})
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 1, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "failed")
        self.assertFalse(Path(self.tmp / "train-count").exists())
        failure = json.loads(Path(status["failure_path"]).read_text())
        self.assertEqual(failure["stage"], "approval")

    def test_restart_attaches_without_second_optimizer_step(self):
        plan, plan_path = build_plan(self.tmp)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        again = subprocess.run(driver_argv(plan_path),
                               cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(again.returncode, 0)
        self.assertEqual(json.loads(again.stdout)["status"], "attached")
        self.assertEqual(len(Path(self.tmp / "train-count").read_text().splitlines()), 1)

    def test_failure_after_train_keeps_checkpoints_and_failure(self):
        plan, plan_path = build_plan(self.tmp, train_exit=1)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 1, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "failed")
        self.assertNotEqual(status["child_exit_code"], 0)
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        names = {item["name"] for item in manifest["artifacts"]}
        self.assertIn("checkpoints.zip", names)
        self.assertIn("failure.json", names)
        self.assertNotIn("lora.zip", names)
        kinds = {item["kind"] for item in status["artifacts"]}
        self.assertIn("report", kinds)
        self.assertIn("log", kinds)
        self.assertIn("model", kinds)
        self.assertTrue(Path(status["failure_path"]).is_file())

    def test_no_wall_timeout_and_no_timeout_keyword(self):
        plan, plan_path = build_plan(self.tmp, train_sleep=1.1)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            started = time.time()
            code, out, err = finish(proc)
            elapsed = time.time() - started
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        self.assertGreater(elapsed, 1.0)
        tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"):
                self.assertFalse(any(keyword.arg == "timeout" for keyword in node.keywords))

    def test_large_artifacts_are_chunked_and_reassemble(self):
        plan, plan_path = build_plan(self.tmp, chunk_size=64)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        status = read_status(plan["status_path"])
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        lora = next(item for item in manifest["artifacts"] if item["name"] == "lora.zip")
        self.assertGreater(len(lora["chunks"]), 1)
        joined = b"".join(Path(chunk["path"]).read_bytes() for chunk in lora["chunks"])
        self.assertEqual(sha_bytes(joined), lora["sha256"])
        for chunk in lora["chunks"]:
            self.assertEqual(status["artifact_hashes"][chunk["path"]], chunk["sha256"])
        flat_lora = [item for item in status["artifacts"]
                     if item["original_name"] == "lora.zip"]
        self.assertGreater(len(flat_lora), 1)
        for item in flat_lora:
            self.assertEqual(item["format"], "archive_chunk")
            self.assertEqual(item["archive_sha256"], lora["sha256"])
            self.assertEqual(item["kind"], "model")
        self.assertEqual(len({item["local_name"] for item in flat_lora}), len(flat_lora))


class ByteCLI:
    """Transport double: status from memory, artifact bytes copied from disk."""

    def __init__(self, status, pid_alive=False):
        self.status = status
        self.pid_alive = pid_alive
        self.download_calls = []
        self.stop_calls = []

    def exec_code(self, session, code, timeout=30.0):
        payload = {"status": self.status, "error": None, "pid_alive": self.pid_alive,
                   "remote_now": time.time(), "log_mtime": None}
        return subprocess.CompletedProcess(
            ["fake"], 0, "WATCHDOG_JSON:" + json.dumps(payload), "")

    def download(self, session, remote_path, local_path, timeout=300.0):
        self.download_calls.append(remote_path)
        source = Path(remote_path)
        if not source.is_file():
            return subprocess.CompletedProcess(["fake"], 1, "", "missing")
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return subprocess.CompletedProcess(["fake"], 0, "", "")

    def sessions(self):
        return subprocess.CompletedProcess(["fake"], 0,
                                           "[colab] No active sessions\n", "")

    def stop(self, session):
        self.stop_calls.append(session)
        return subprocess.CompletedProcess(["fake"], 0, "", "")


def public_watchdog(status, state_dir, *, until_preflight=False, pid_alive=False):
    cli = ByteCLI(status, pid_alive=pid_alive)
    wd = WT.Watchdog(
        session=status["session"], job_dir="/content/job",
        job_uuid=status["job_uuid"], state_dir=Path(state_dir), cli=cli,
        poll_interval=0.0, rpc_timeout=5.0, max_polls=1,
        sleeper=lambda seconds: None,
        expected_source_hash=status["source_hash"],
        expected_package_hash=status["package_hash"],
        until_preflight=until_preflight)
    return wd, cli


class DriverWatchdogInteropTests(unittest.TestCase):
    """The watchdog must accept the real driver status shapes end to end."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reviewed-interop-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_driver(self, tag, **kwargs):
        plan, plan_path = build_plan(self.tmp / tag, **kwargs)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        return plan, code, out, err, read_status(plan["status_path"])

    def test_public_watchdog_accepts_real_terminal_status(self):
        for chunk_size in (64, 10_000_000):
            with self.subTest(chunk_size=chunk_size):
                plan, code, out, err, status = self._run_driver(
                    "complete-%s" % chunk_size, chunk_size=chunk_size)
                self.assertEqual(code, 0, (out, err))
                self.assertEqual(status["state"], "complete")
                wd, cli = public_watchdog(status, self.tmp / ("watch-%s" % chunk_size))
                self.assertEqual(wd.run(), 0)
                self.assertEqual(cli.stop_calls, [plan["session"]])
                explicit = [item["path"] for item in status["artifacts"]
                            if item.get("required", True)]
                expected = set(explicit) | {status["download_manifest"]}
                self.assertEqual(sorted(cli.download_calls), sorted(expected))
                if chunk_size < 1024:
                    self.assertNotIn(status["log_path"], cli.download_calls)
                for item in status["artifacts"]:
                    destination = Path(wd.artifact_dir) / item["local_name"]
                    self.assertEqual(sha_file(destination), item["sha256"])
                kinds = {item["kind"] for item in status["artifacts"]}
                self.assertEqual(kinds, {"model", "report", "log"})

    def test_public_watchdog_salvages_real_failed_status(self):
        for chunk_size in (64, 10_000_000):
            with self.subTest(chunk_size=chunk_size):
                plan, code, out, err, status = self._run_driver(
                    "failed-%s" % chunk_size, train_exit=1, chunk_size=chunk_size)
                self.assertEqual(code, 1, (out, err))
                self.assertEqual(status["state"], "failed")
                wd, cli = public_watchdog(status, self.tmp / ("watch-failed-%s" % chunk_size))
                self.assertEqual(wd.run(), 1)
                self.assertEqual(cli.stop_calls, [plan["session"]])
                names = {Path(path).name for path in cli.download_calls}
                self.assertTrue(any(name.startswith("checkpoints") for name in names))
                self.assertTrue(any(name.startswith("failure.json") for name in names))
                if chunk_size < 1024:
                    self.assertNotIn(status["log_path"], cli.download_calls)
                for item in status["artifacts"]:
                    destination = Path(wd.artifact_dir) / item["local_name"]
                    self.assertEqual(sha_file(destination), item["sha256"])

    def test_handoff_snapshot_hash_is_immutable(self):
        plan, plan_path = build_plan(self.tmp / "handoff", chunk_size=64)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            snapshot = Path(awaiting["log_snapshot_path"])
            published = awaiting["artifact_hashes"][str(snapshot)]
            self.assertEqual(published, sha_file(snapshot))
            self.assertEqual(awaiting["log_snapshot_sha256"], published)
            self.assertNotIn(awaiting["log_path"], awaiting["artifact_hashes"])
            wd, cli = public_watchdog(awaiting, self.tmp / "watch-handoff",
                                      until_preflight=True, pid_alive=True)
            self.assertEqual(wd.run(), 10)
            self.assertEqual(cli.stop_calls, [])
            self.assertEqual(sorted(cli.download_calls),
                             sorted(item["path"] for item in awaiting["artifacts"]))
            self.assertNotIn(awaiting["log_path"], cli.download_calls)
            self.assertEqual(sha_file(Path(wd.artifact_dir) / snapshot.name), published)
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(sha_file(snapshot), published)
        self.assertNotEqual(sha_file(awaiting["log_path"]), published)


class FailureEvidenceTests(unittest.TestCase):
    """A failed stage must leave its real runner evidence behind, and the
    published evidence must be hash-verified before the session is stopped."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reviewed-evidence-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_to_failure(self, tag, **kwargs):
        plan, plan_path = build_plan(self.tmp / tag, **kwargs)
        code, out, err = finish(start(plan_path))
        return plan, plan_path, code, out, err, read_status(plan["status_path"])

    def _run_to_train_failure(self, tag, **kwargs):
        plan, plan_path = build_plan(self.tmp / tag, **kwargs)
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        return plan, plan_path, code, out, err, read_status(plan["status_path"])

    def _by_label(self, diagnostics, label):
        return [item for item in diagnostics if item.get("label") == label]

    def _capture_evidence(self, plan, status, tag):
        target = os.environ.get("REVIEWED_JOB_EVIDENCE_DIR")
        if not target:
            return
        dest = Path(target) / tag
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(plan["status_path"], dest / "status.json")
        shutil.copyfile(status["download_manifest"], dest / "download-manifest.json")
        shutil.copyfile(status["failure_path"], dest / "failure.json")
        facts = {}
        for item in status["artifacts"]:
            source = Path(item["path"])
            if not source.is_file():
                continue
            copied = dest / ("artifact-" + item["local_name"])
            shutil.copyfile(source, copied)
            facts[item["local_name"]] = {
                "bytes": copied.stat().st_size, "sha256": sha_file(copied),
                "source_path": item["path"], "role": item.get("role"),
                "stage": item.get("stage"),
            }
        (dest / "artifact-hashes.json").write_text(
            json.dumps(facts, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    def test_failed_preflight_preserves_failure_identity_and_events(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-evidence", preflight_mode="preflight_fail", preflight_exit=2)
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(status["state"], "failed")
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        self.assertFalse(manifest["complete"])
        names = {item["name"] for item in manifest["artifacts"]}
        self.assertTrue({"preflight-failure.json", "preflight-events.jsonl",
                         "preflight-identity-measurement.json",
                         "failure.json"}.issubset(names))
        self.assertNotIn("preflight-report.json", names)
        absent = {item["key"]: item for item in manifest["expected_absent"]}
        self.assertIn("preflight_report", absent)
        self.assertTrue(absent["preflight_report"]["reason"])
        self.assertNotIn("preflight-report.json", manifest["missing"])
        self.assertNotIn("preflight-failure.json", manifest["missing"])

        preflight_out = Path(plan["paths"]["preflight_report"]).parent
        sources = {
            "preflight_runner_failure": preflight_out / "preflight-failure.json",
            "preflight_events": preflight_out / "events.jsonl",
            "identity_measurement_preflight":
                preflight_out / "identity-measurement.json",
        }
        roles = {
            "preflight_runner_failure": "runner_failure",
            "preflight_events": "stage_events",
            "identity_measurement_preflight": "identity_measurement",
        }
        locals_ = {
            "preflight_runner_failure": "preflight-failure.json",
            "preflight_events": "preflight-events.jsonl",
            "identity_measurement_preflight":
                "preflight-identity-measurement.json",
        }
        for label, source in sources.items():
            item = self._by_label(status["artifacts"], label)[0]
            self.assertEqual(item["stage"], "preflight")
            self.assertEqual(item["role"], roles[label])
            self.assertEqual(item["bytes"], source.stat().st_size)
            self.assertEqual(item["sha256"], sha_file(source))
            self.assertEqual(item["local_name"], locals_[label])
            self.assertEqual(sha_file(item["path"]), item["sha256"])

        failure = json.loads(Path(status["failure_path"]).read_text())
        for key in ("job_uuid", "session", "source_hash", "package_hash",
                    "plan_sha256"):
            self.assertTrue(failure[key], key)
        self.assertEqual(failure["job_uuid"], plan["job_uuid"])
        self.assertEqual(failure["source_hash"], plan["source_hash"])
        self.assertEqual(failure["package_hash"], plan["package_hash"])
        self.assertEqual(failure["plan_sha256"], sha_file(plan_path))
        self.assertEqual(failure["stage"], "preflight")
        for label in ("preflight_runner_failure", "preflight_events",
                      "identity_measurement_preflight"):
            entry = self._by_label(failure["diagnostics"], label)
            self.assertEqual(len(entry), 1, label)
            self.assertEqual(entry[0]["status"], "present")
            self.assertEqual(entry[0]["sha256"],
                             sha_file(entry[0]["path"]))
            self.assertEqual(entry[0]["stage"], "preflight")
        self.assertEqual(failure["diagnostic_paths"]["preflight_runner_failure"],
                         str(preflight_out / "preflight-failure.json"))

        self._capture_evidence(plan, status, "failed-preflight")

        wd, cli = public_watchdog(status, self.tmp / "watch-preflight")
        self.assertEqual(wd.run(), 1)
        self.assertEqual(cli.stop_calls, [plan["session"]])
        expected = {item["path"] for item in status["artifacts"]}
        expected.add(status["download_manifest"])
        self.assertEqual(sorted(cli.download_calls), sorted(expected))
        for item in status["artifacts"]:
            destination = Path(wd.artifact_dir) / item["local_name"]
            self.assertEqual(sha_file(destination), item["sha256"])
        self.assertEqual(len({item["local_name"] for item in status["artifacts"]}),
                         len(status["artifacts"]))

    def test_stage_that_never_ran_is_expected_absent_not_missing(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-never-ran", package_exit=1)
        self.assertEqual(code, 1, (out, err))
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        self.assertFalse(manifest["complete"])
        absent = {item["key"] for item in manifest["expected_absent"]}
        for key in ("preflight_report", "preflight_runner_failure",
                    "preflight_events", "identity_measurement_preflight"):
            self.assertIn(key, absent)
        self.assertNotIn("preflight-report.json", manifest["missing"])
        self.assertNotIn("preflight-failure.json", manifest["missing"])
        failure = json.loads(Path(status["failure_path"]).read_text())
        for label in ("preflight_report", "preflight_runner_failure",
                      "preflight_events", "identity_measurement_preflight"):
            entry = self._by_label(failure["diagnostics"], label)
            self.assertEqual(len(entry), 1, label)
            self.assertEqual(entry[0]["status"], "expected_absent", label)
            self.assertTrue(entry[0]["reason"])
            self.assertNotIn("sha256", entry[0])

    def test_preflight_that_died_without_evidence_is_expected_absent(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-bare", preflight_mode="preflight_bare_fail",
            preflight_exit=137)
        self.assertEqual(code, 1, (out, err))
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        absent = {item["key"] for item in manifest["expected_absent"]}
        for key in ("preflight_report", "preflight_runner_failure",
                    "preflight_events", "identity_measurement_preflight"):
            self.assertIn(key, absent)
        for name in ("preflight-failure.json", "preflight-events.jsonl",
                     "preflight-identity-measurement.json"):
            self.assertNotIn(name, manifest["missing"])
        failure = json.loads(Path(status["failure_path"]).read_text())
        for label in ("preflight_runner_failure", "preflight_events",
                      "identity_measurement_preflight"):
            entry = self._by_label(failure["diagnostics"], label)
            self.assertEqual(entry[0]["status"], "expected_absent", label)
            self.assertTrue(entry[0]["reason"])
        self._capture_evidence(plan, status, "missing-evidence")
        wd, cli = public_watchdog(status, self.tmp / "watch-bare")
        self.assertEqual(wd.run(), 1)
        self.assertEqual(cli.stop_calls, [plan["session"]])

    def test_stage_that_succeeded_without_its_report_is_missing(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-no-report", preflight_mode="preflight_ok_no_report")
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(status["state"], "failed")
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        absent = {item["key"] for item in manifest["expected_absent"]}
        self.assertNotIn("preflight_report", absent)
        for name in ("preflight-report.json", "preflight-failure.json",
                     "preflight-events.jsonl",
                     "preflight-identity-measurement.json"):
            self.assertIn(name, manifest["missing"])
        failure = json.loads(Path(status["failure_path"]).read_text())
        self.assertEqual(failure["stage"], "preflight")
        for label in ("preflight_report", "preflight_runner_failure",
                      "preflight_events", "identity_measurement_preflight"):
            entry = self._by_label(failure["diagnostics"], label)
            self.assertEqual(entry[0]["status"], "missing", label)
        wd, cli = public_watchdog(status, self.tmp / "watch-no-report")
        self.assertEqual(wd.run(), 1)
        self.assertEqual(cli.stop_calls, [plan["session"]])

    def test_missing_published_diagnostic_blocks_stop(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-missing-published", preflight_mode="preflight_fail",
            preflight_exit=2)
        self.assertEqual(code, 1, (out, err))
        victim = next(item for item in status["artifacts"]
                      if item["role"] == "runner_failure")
        Path(victim["path"]).unlink()
        wd, cli = public_watchdog(status, self.tmp / "watch-missing")
        self.assertEqual(wd.run(), 3)
        self.assertEqual(cli.stop_calls, [])

    def test_tampered_published_diagnostic_blocks_stop(self):
        plan, plan_path, code, out, err, status = self._run_to_failure(
            "preflight-tampered", preflight_mode="preflight_fail",
            preflight_exit=2)
        self.assertEqual(code, 1, (out, err))
        victim = next(item for item in status["artifacts"]
                      if item["role"] == "identity_measurement")
        with Path(victim["path"]).open("ab") as handle:
            handle.write(b"\n")
        self.assertNotEqual(sha_file(victim["path"]), victim["sha256"])
        wd, cli = public_watchdog(status, self.tmp / "watch-tampered")
        self.assertEqual(wd.run(), 3)
        self.assertEqual(cli.stop_calls, [])

    def test_successful_run_stays_complete_with_no_absent_claims(self):
        plan, plan_path = build_plan(self.tmp / "success")
        proc = start(plan_path)
        try:
            awaiting = wait_status(plan["status_path"],
                                   lambda s: s.get("phase") == "awaiting_approval")
            write_approval(plan, awaiting)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 0, (out, err))
        status = read_status(plan["status_path"])
        self.assertEqual(status["state"], "complete")
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["missing"], [])
        self.assertEqual(manifest["expected_absent"], [])
        names = {item["name"] for item in manifest["artifacts"]}
        self.assertIn("train-events.jsonl", names)
        self.assertNotIn("events.jsonl", names)
        roles = {item["role"] for item in status["artifacts"]}
        self.assertNotIn("runner_failure", roles)
        self.assertNotIn("identity_measurement", roles)
        for item in status["artifacts"]:
            self.assertEqual(sha_file(item["path"]), item["sha256"])

    def test_failed_train_salvages_checkpoints_and_train_diagnostics(self):
        plan, plan_path, code, out, err, status = self._run_to_train_failure(
            "train-evidence", train_exit=1)
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(status["state"], "failed")
        manifest = json.loads(Path(status["download_manifest"]).read_text())
        names = {item["name"] for item in manifest["artifacts"]}
        for name in ("checkpoints.zip", "train-run-failure.json",
                     "train-events.jsonl", "train-identity-measurement.json",
                     "preflight-report.json"):
            self.assertIn(name, names)
        absent = {item["key"] for item in manifest["expected_absent"]}
        self.assertIn("run_report", absent)
        self.assertNotIn("train-run-failure.json", manifest["missing"])
        failure = json.loads(Path(status["failure_path"]).read_text())
        self.assertEqual(failure["stage"], "train")
        entry = self._by_label(failure["diagnostics"], "train_runner_failure")[0]
        self.assertEqual(entry["status"], "present")
        self.assertEqual(entry["stage"], "train")
        self.assertEqual(entry["sha256"], sha_file(entry["path"]))
        preflight = self._by_label(failure["diagnostics"], "preflight_report")[0]
        self.assertEqual(preflight["status"], "present")
        self._capture_evidence(plan, status, "failed-train")
        wd, cli = public_watchdog(status, self.tmp / "watch-train")
        self.assertEqual(wd.run(), 1)
        self.assertEqual(cli.stop_calls, [plan["session"]])
        for item in status["artifacts"]:
            destination = Path(wd.artifact_dir) / item["local_name"]
            self.assertEqual(sha_file(destination), item["sha256"])


class PlanBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reviewed-binding-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extra_declared_source_is_closure_verified(self):
        plan, plan_path = build_plan(self.tmp, generated_package=True, with_stages=True)
        raw = json.loads(Path(plan_path).read_text())
        gate_script = raw["commands"]["gate"][1]
        raw["sources"]["gate"] = {"path": gate_script, "sha256": "0" * 64}
        Path(plan_path).write_text(json.dumps(raw, indent=1, sort_keys=True))
        bad = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                             cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2, bad.stderr)
        self.assertEqual(json.loads(bad.stdout)["status"], "closure_invalid")
        self.assertFalse(Path(self.tmp / "guard-ran").exists())
        self.assertFalse(Path(plan["package"]["manifest"]["path"]).exists())
        self.assertFalse(Path(plan["status_path"]).exists())

        raw["sources"]["gate"]["sha256"] = sha_file(gate_script)
        Path(plan_path).write_text(json.dumps(raw, indent=1, sort_keys=True))
        good = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                              cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)["status"], "pass")

        raw["sources"].pop("deps")
        Path(plan_path).write_text(json.dumps(raw, indent=1, sort_keys=True))
        missing = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                                 cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["status"], "plan_invalid")

    def test_duplicate_critical_train_flags_are_rejected(self):
        for flag in ("--manifest", "--contract", "--preflight-report", "--approval"):
            with self.subTest(flag=flag):
                tmp = self.tmp / flag.strip("-")
                plan, plan_path = build_plan(tmp)
                raw = json.loads(Path(plan_path).read_text())
                decoy = write(tmp / "decoy.json", "{}\n")
                raw["commands"]["train"] = list(raw["commands"]["train"]) + [
                    flag, str(decoy)]
                Path(plan_path).write_text(json.dumps(raw, indent=1, sort_keys=True))
                check = subprocess.run(driver_argv(plan_path, ["--check-plan"]),
                                       cwd=str(ROOT), capture_output=True, text=True)
                self.assertEqual(check.returncode, 2, check.stderr)
                self.assertEqual(json.loads(check.stdout)["status"], "plan_invalid")
                self.assertFalse(Path(tmp / "install-ran").exists())
                self.assertFalse(Path(plan["status_path"]).exists())

    def test_plan_is_parsed_once_from_verified_bytes(self):
        plan, plan_path = build_plan(self.tmp, preflight_exit=1)
        approved = json.loads(Path(plan_path).read_text())
        approved["job_uuid"] = "job-approved"
        approved["session"] = "approved-session"
        approved_bytes = json.dumps(approved, indent=1, sort_keys=True).encode()
        swapped = json.loads(Path(plan_path).read_text())
        swapped["job_uuid"] = "job-swapped"
        swapped["session"] = "swapped-session"
        swapped_bytes = json.dumps(swapped, indent=1, sort_keys=True).encode()
        fifo = self.tmp / "plan.fifo"
        os.mkfifo(str(fifo))
        served = []

        def serve():
            for payload in (approved_bytes, swapped_bytes):
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    try:
                        handle = os.open(str(fifo), os.O_WRONLY | os.O_NONBLOCK)
                    except OSError:
                        time.sleep(0.01)
                        continue
                    try:
                        os.write(handle, payload)
                    finally:
                        os.close(handle)
                    served.append(payload)
                    break
                time.sleep(0.2)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        proc = subprocess.Popen(
            [PY, str(DRIVER), "--plan", str(fifo),
             "--plan-sha256", sha_bytes(approved_bytes)],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            status = wait_status(plan["status_path"],
                                 lambda s: s.get("state") == "failed", timeout=15.0)
            code, out, err = finish(proc)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(code, 1, (out, err))
        self.assertEqual(status["job_uuid"], "job-approved")
        self.assertEqual(status["session"], "approved-session")
        self.assertEqual(status["plan_sha256"], sha_bytes(approved_bytes))
        self.assertEqual(served, [approved_bytes])


class RealRunnerApprovalTests(unittest.TestCase):
    def test_real_verify_approval_binds_report_and_export(self):
        package = TR.Package()
        package.manifest = {
            "inputs": {
                "dataset": {"sha256_bytes": "dataset", "sha256_rows": "rows",
                            "row_facts": {"rows": 1}},
                "recipe_sha256": "recipe",
                "runner": {"sha256": "runner", "deps_sha256": "deps"},
            },
            "recipe": {"base_revision": "base", "tokenizer_revision": "tokenizer",
                       "tokenizer_chat_template_sha256": "template",
                       "tokenizer_config_sha256": "config"},
        }
        package.contract = {"export": {"gguf": "q4_k_m", "merged_16bit": True}}
        package.manifest_sha256 = "manifest"
        package.contract_sha256 = "contract"
        package.validation_block = {"sha256_bytes": "validation", "rows": 1}
        package.facts = {"controls_sha256": "controls",
                         "inventory": {"sha256": "inventory",
                                       "fragment_sha256": "fragment",
                                       "receipt_sha256": "receipt"}}
        report = dict(TR.expected_package_facts(package))
        report.update({"schema": TR.PREFLIGHT_SCHEMA, "status": "pass",
                       "manifest_sha256": "manifest", "contract_sha256": "contract"})
        report_bytes = json.dumps(report, sort_keys=True).encode()
        approval = {
            "schema": TR.APPROVAL_SCHEMA,
            "decision": "approved",
            "reviewer": "test",
            "approved_at": "2026-10-30T00:00:00Z",
            "manifest_sha256": "manifest",
            "contract_sha256": "contract",
            "preflight_report_sha256": sha_bytes(report_bytes),
            "export": package.contract["export"],
        }
        issues = TR.new_issues()
        TR.verify_approval(approval, json.dumps(approval).encode(), report,
                           report_bytes, package, issues)
        self.assertTrue(issues.ok, issues.failures)
        bad = deepcopy(approval)
        bad["export"] = {"gguf": "q8_0", "merged_16bit": True}
        issues = TR.new_issues()
        TR.verify_approval(bad, json.dumps(bad).encode(), report, report_bytes,
                           package, issues)
        self.assertFalse(issues.ok)


if __name__ == "__main__":
    unittest.main()
