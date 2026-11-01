"""Shared fixtures for the independent driver/watchdog interop probes.

No repo source is imported for the driver under test: it is spawned as an OS
process exactly as the parent will spawn it. The watchdog IS imported from the
current tree, and every probe records the watchdog file hash it ran against,
because that file is being repaired concurrently.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "artifacts" / "colab" / "run_reviewed_job.py"
WATCHER = ROOT / "artifacts" / "colab" / "watch_training.py"
PY = sys.executable


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def wait_status(path, predicate, timeout=20.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        if Path(path).is_file():
            try:
                last = read_json(path)
            except Exception:
                last = None
            if last is not None and predicate(last):
                return last
        time.sleep(0.02)
    raise AssertionError("status predicate not met; last=%r" % (last,))


# ----------------------------------------------------------------- fixtures

FIXTURE_RUNNER = r'''
import hashlib, json
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

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_package(manifest, contract, **kwargs):
    m = json.loads(Path(manifest).read_text())
    c = json.loads(Path(contract).read_text())
    return SimpleNamespace(
        manifest=m, contract=c,
        manifest_sha256=_sha(manifest), contract_sha256=_sha(contract),
        validation_block={}, issues=new_issues(),
        facts={"controls_sha256": "controls",
               "inventory": {"sha256": "inventory",
                             "fragment_sha256": "fragment",
                             "receipt_sha256": "receipt"}})

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
        issues.fail("report", "report bytes mismatch")
    if report.get("status") != "pass":
        issues.fail("report_status", "report is not passing")
    if approval.get("export") != package.contract.get("export"):
        issues.fail("export", "export mismatch")
'''

STAGE = r'''
import json, sys, time, zipfile
from pathlib import Path

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")

mode = sys.argv[1]
if mode == "gate":
    write(sys.argv[2], {"schema": "prepare-training-manifest/1",
                        "status": "ready-to-launch", "release_id": sys.argv[3]})
elif mode == "derive":
    write(sys.argv[2], {"schema": "training-runner-contract/1",
                        "export": {"gguf": "q4_k_m", "merged_16bit": True}})
elif mode == "package":
    code = int(sys.argv[3])
    write(sys.argv[2], {"schema": "training-package-check/1",
                        "status": "pass" if code == 0 else "fail"})
    sys.exit(code)
elif mode == "freeze":
    write(sys.argv[2], {"schema": "runtime-freeze/1", "versions": {"torch": "test"}})
    Path(sys.argv[3]).write_text("torch==test\n")
    sys.exit(int(sys.argv[4]) if len(sys.argv) > 4 else 0)
elif mode == "preflight":
    report, code, manifest, contract = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
    write(report, {"schema": "training-preflight-report/1", "status": "pass",
                   "manifest_sha256": manifest, "contract_sha256": contract})
    sys.exit(code)
elif mode == "train":
    out, counter, report, code = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), int(sys.argv[5])
    counter.parent.mkdir(parents=True, exist_ok=True)
    with counter.open("a") as handle:
        handle.write("call\n")
    checkpoint = out / "checkpoints" / "checkpoint-1"
    checkpoint.mkdir(parents=True, exist_ok=True)
    (checkpoint / "adapter_model.safetensors").write_bytes(b"checkpoint" * 80)
    (checkpoint / "optimizer.pt").write_bytes(b"optimizer" * 80)
    if code == 0:
        skip = "skip-report" in sys.argv
        lora = out / "lora"
        lora.mkdir(parents=True, exist_ok=True)
        (lora / "adapter_model.safetensors").write_bytes(b"adapter" * 120)
        (lora / "adapter_config.json").write_text("{}\n")
        merged = out / "merged_16bit"
        merged.mkdir(parents=True, exist_ok=True)
        (merged / "model.safetensors").write_bytes(b"merged" * 200)
        (merged / "config.json").write_text("{}\n")
        gguf_dir = out / "gguf"
        gguf_dir.mkdir(parents=True, exist_ok=True)
        gguf = gguf_dir / "reviewed.q4_k_m.gguf"
        gguf.write_bytes(b"gguf" * 400)
        with zipfile.ZipFile(out / "reviewed_q4_k_m.zip", "w") as archive:
            archive.write(gguf, gguf.name)
        if not skip:
            write(report, {"schema": "training-run-report/1", "status": "pass"})
            (out / "events.jsonl").write_text('{"event": "train_end"}\n')
    sys.exit(code)
'''

GATE_SCRIPT = r'''
import json, sys
from pathlib import Path
target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps({"schema": "prepare-training-manifest/1",
                              "status": "ready-to-launch",
                              "release_id": "unverified-gate"}) + "\n")
'''

INSTALL = r'''
import sys
from pathlib import Path
Path(sys.argv[1]).write_text("installed\n")
sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
'''


def build_plan(tmp, *, package_exit=0, preflight_exit=0, train_exit=0,
               install_exit=0, freeze_exit=0, train_skip_report=False,
               chunk_size=256, extra_source=False, wrong_runner_hash=False,
               gate_generated=True):
    """A plan shaped like the real runner's CLI, not like the unit-test fixture."""
    tmp = Path(tmp)
    job = tmp / "job"
    out = tmp / "out"
    job.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    runner = write(tmp / "runner.py", FIXTURE_RUNNER)
    install = write(tmp / "install.py", INSTALL)
    deps = write(tmp / "requirements-locked.txt", "torch==test\ntrl==test\n")
    stage = write(tmp / "stage.py", STAGE)
    gate_script = write(tmp / "gate_script.py", GATE_SCRIPT)
    manifest = out / "manifest.json"
    contract = out / "contract.json"
    if gate_generated:
        manifest.unlink(missing_ok=True)
        contract.unlink(missing_ok=True)
    else:
        write(manifest, json.dumps({"schema": "prepare-training-manifest/1",
                                    "status": "ready-to-launch",
                                    "release_id": "probe"}) + "\n")
        write(contract, json.dumps({"schema": "training-runner-contract/1",
                                    "export": {"gguf": "q4_k_m",
                                               "merged_16bit": True}}) + "\n")

    paths = {
        "package_check": out / "package-check.json",
        "preflight_report": out / "preflight-report.json",
        "runtime_freeze_json": out / "runtime-freeze.json",
        "runtime_freeze_txt": out / "runtime-freeze.txt",
        "run_report": out / "training-run-report.json",
        "events": out / "events.jsonl",
        "failure": out / "failure.json",
        "download_manifest": job / "download-manifest.json",
        "lora_dir": out / "lora",
        "merged_dir": out / "merged_16bit",
        "checkpoints_dir": out / "checkpoints",
        "gguf_zip": out / "reviewed_q4_k_m.zip",
        "approval": job / "approval.json",
    }
    sources = {
        "runner": {"path": str(runner),
                   "sha256": ("0" * 64 if wrong_runner_hash else sha_file(runner))},
        "install": {"path": str(install), "sha256": sha_file(install)},
        "deps": {"path": str(deps), "sha256": sha_file(deps)},
    }
    if extra_source:
        # Declared by the plan author as the executed gate. The declared hash is
        # deliberately wrong: the driver must not silently accept it.
        sources["gate"] = {"path": str(gate_script), "sha256": "0" * 64}
    package = {
        "manifest": ({"path": str(manifest), "generated": True} if gate_generated
                     else {"path": str(manifest), "sha256": sha_file(manifest)}),
        "contract": ({"path": str(contract), "generated": True} if gate_generated
                     else {"path": str(contract), "sha256": sha_file(contract)}),
        "lock": {"path": str(deps), "sha256": sha_file(deps)},
        "lock_pins": 2,
    }
    commands = {
        "install": [PY, str(install), str(tmp / "install-ran"), str(install_exit)],
        "freeze": [[PY, str(stage), "freeze", str(paths["runtime_freeze_json"]),
                    str(paths["runtime_freeze_txt"]), str(freeze_exit)]],
        "package": [PY, str(stage), "package", str(paths["package_check"]),
                    str(package_exit)],
        "preflight": [PY, str(stage), "preflight", str(paths["preflight_report"]),
                      str(preflight_exit), "manifest-sha", "contract-sha"],
        "train": [PY, str(stage), "train", str(out), str(tmp / "train-count"),
                  str(paths["run_report"]), str(train_exit),
                  *(["skip-report"] if train_skip_report else []),
                  "--manifest", str(manifest), "--contract", str(contract),
                  "--preflight-report", str(paths["preflight_report"]),
                  "--approval", str(paths["approval"])],
    }
    if gate_generated:
        commands["gate"] = [PY, str(gate_script), str(manifest)]
        commands["derive_contract"] = [PY, str(stage), "derive", str(contract)]
    plan = {
        "schema": "reviewed-job-plan/1",
        "job_uuid": "job-probe-0001",
        "session": "probe-session",
        "source_hash": sha_file(DRIVER),
        "package_hash": sha_bytes(b"certified-archive-91a1137c"),
        "job_dir": str(job),
        "status_path": str(job / "status.json"),
        "log_path": str(job / "job.log"),
        "heartbeat_seconds": 0.05,
        "approval_poll_seconds": 0.01,
        "chunk_size_bytes": chunk_size,
        "sources": sources,
        "package": package,
        "commands": commands,
        "paths": {key: str(value) for key, value in paths.items()},
    }
    plan_path = write(tmp / "plan.json", json.dumps(plan, indent=1, sort_keys=True))
    return plan, plan_path


def driver_argv(plan_path, extra=()):
    return [PY, str(DRIVER), "--plan", str(plan_path),
            "--plan-sha256", sha_file(plan_path), *extra]


def start(plan_path):
    return subprocess.Popen(driver_argv(plan_path), cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(proc, timeout=30.0):
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise AssertionError("driver did not finish; stdout=%r stderr=%r" % (out, err))
    return proc.returncode, out, err


def kill(proc):
    if proc.poll() is None:
        proc.kill()
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out, err


def approval_payload(plan, status):
    contract = read_json(plan["package"]["contract"]["path"])
    return {
        "schema": "training-preflight-approval/1",
        "decision": "approved",
        "reviewer": "probe-reviewer",
        "approved_at": "2026-10-30T00:00:00Z",
        "manifest_sha256": sha_file(plan["package"]["manifest"]["path"]),
        "contract_sha256": sha_file(plan["package"]["contract"]["path"]),
        "preflight_report_sha256": status["preflight_report_sha256"],
        "export": contract["export"],
    }


def write_approval(plan, status):
    payload = approval_payload(plan, status)
    write(plan["paths"]["approval"], json.dumps(payload, indent=1, sort_keys=True))
    return payload


def import_watcher():
    sys.path.insert(0, str(WATCHER.parent))
    import watch_training as WT  # noqa: E402

    return WT


class FakeCLI:
    """Fake transport: reads the real status bytes, copies real artifact bytes."""

    def __init__(self, status_path, pid_alive=False):
        self.status_path = Path(status_path)
        self.pid_alive = pid_alive
        self.calls = []

    def exec_code(self, session, code, timeout=30.0):
        self.calls.append(("exec_code", session))
        try:
            status = read_json(self.status_path)
        except Exception as exc:
            payload = {"status": None, "error": repr(exc), "pid_alive": None,
                       "remote_now": time.time(), "log_mtime": None}
        else:
            payload = {"status": status, "error": None, "pid_alive": self.pid_alive,
                       "remote_now": time.time(), "log_mtime": None}
        return SimpleNamespace(returncode=0,
                               stdout="WATCHDOG_JSON:" + json.dumps(payload) + "\n",
                               stderr="")

    def download(self, session, remote_path, local_path, timeout=300.0):
        self.calls.append(("download", remote_path))
        src = Path(remote_path)
        if not src.is_file():
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def stop(self, session):
        self.calls.append(("stop", session))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def sessions(self):
        self.calls.append(("sessions", None))
        return SimpleNamespace(returncode=0, stdout="[colab] No active sessions\n",
                               stderr="")


def make_watchdog(plan, state_dir, *, until_preflight=False, pid_alive=False,
                  artifact_dir=None):
    WT = import_watcher()
    cli = FakeCLI(plan["status_path"], pid_alive=pid_alive)
    watch = WT.Watchdog(
        session=plan["session"], job_dir=plan["job_dir"],
        job_uuid=plan["job_uuid"], state_dir=Path(state_dir),
        cli=cli, poll_interval=0.01, rpc_timeout=5.0, stale_heartbeat=300.0,
        expected_source_hash=plan["source_hash"],
        expected_package_hash=plan["package_hash"],
        artifact_dir=Path(artifact_dir) if artifact_dir else None,
        max_polls=1, sleeper=lambda seconds: None,
        until_preflight=until_preflight)
    return WT, watch, cli


def environment():
    return {
        "driver": str(DRIVER), "driver_sha256": sha_file(DRIVER),
        "watcher": str(WATCHER), "watcher_sha256": sha_file(WATCHER),
        "python": sys.version.split()[0],
    }


def new_tmp(label):
    return Path(tempfile.mkdtemp(prefix="driver-probe-%s-" % label))


def cleanup(path):
    shutil.rmtree(str(path), ignore_errors=True)
