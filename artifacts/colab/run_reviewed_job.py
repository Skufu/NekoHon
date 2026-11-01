#!/usr/bin/env python3
"""Finite OS-background driver for one reviewed Qwen training attempt.

The driver runs on the VM as a normal OS process, launched by a short Jupyter
exec with ``Popen(..., start_new_session=True)``. It never runs inside the
kernel, never allocates a Colab session, never uploads weights, and never
decides that a preflight is approved.

Sequence: verify the caller-supplied plan and every file hash; claim the
one-attempt marker with O_EXCL; install from the exact lock; write and check
the runtime freeze; run the runner's package check; run preflight; wait for the
parent's approval artifact; verify that approval with the real runner's
``verify_approval``; run train once; package and chunk exports. No timeout is
applied to install, preflight, approval waiting, or train.

Status is an atomic JSON file. Required fields:
``job_uuid, session, source_hash, package_hash, pid, state, heartbeat_at,
log_path``. ``pid`` is this supervisor. After a terminal state the process
exits, so a watcher sees a dead PID. A watcher that uses ``os.kill(pid, 0)``
should also read ``/proc/<pid>/stat`` and treat state ``Z`` as dead.

Identity:
- ``source_hash`` is the SHA-256 of this driver file. The plan must carry the
  same value. A parent can pass it to the watcher as ``--expected-source-hash``.
- ``package_hash`` is the SHA-256 of the approved training-package archive,
  computed outside and supplied by the caller. The driver does not recompute
  it from the archive, so it is not self-referential. A parent can pass it as
  ``--expected-package-hash``.
- The runner/install/deps and manifest/contract/lock file hashes are verified
  separately before any executable stage.

Failure after train starts still packages whatever checkpoints, LoRA, merged
files, or GGUF exist. The sole trained checkpoint is not discarded because a
run report is missing.

Failure evidence: before packaging a failed run the driver hashes every
runner diagnostic that exists where the runner wrote it. Paths are derived
from the plan's report paths (preflight-out from the preflight report,
train-out from the run report), so no new plan field is required: the runner's
failure record (preflight-failure.json / run-failure.json), its stage event log
(events.jsonl) and its identity measurement (identity-measurement.json).
Local names are explicit (preflight-events.jsonl, train-events.jsonl,
preflight-identity-measurement.json, train-identity-measurement.json) so a
flattened download never overwrites one stage with the other. failure.json
carries job/source/package/plan identity and every diagnostic path with size,
hash, stage, and role. An absent artifact is recorded as expected_absent when
the failed stage accounts for it (the producer never ran, the producer failed,
or a failure record belongs to another stage), and as missing only when the
producer succeeded or an earlier stage had already completed. Nothing is
published or invented for a file that is not present.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PLAN_SCHEMA = "reviewed-job-plan/1"
STATUS_SCHEMA = "reviewed-job-status/1"
FAILURE_SCHEMA = "reviewed-job-failure/1"
DOWNLOADS_SCHEMA = "reviewed-job-downloads/1"
APPROVAL_REQUEST_SCHEMA = "reviewed-job-approval-request/1"
DEFAULT_CHUNK_BYTES = 128 * 1024 * 1024

# Stage order used only to classify an absent artifact as "the run never got
# there" (expected_absent) rather than "it should have existed" (missing).
STAGE_SEQUENCE = ("guard", "gate", "derive_contract", "package", "install",
                  "runtime_freeze", "preflight", "approval", "train", "export")

# key: producing stage (used only to classify a failed stage's absent output)
PLAN_ARTIFACT_STAGES = {
    "package_check": "package",
    "runtime_freeze_json": "runtime_freeze",
    "runtime_freeze_txt": "runtime_freeze",
    "preflight_report": "preflight",
    "run_report": "train",
    "events": "train",
}


class PlanError(Exception):
    pass


class StageError(Exception):
    def __init__(self, stage, message, exit_code=1, stage_failed=True):
        super().__init__("%s: %s" % (stage, message))
        self.stage = stage
        self.message = message
        self.exit_code = int(exit_code or 1)
        self.stage_failed = bool(stage_failed)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=1, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_json(path, label):
    path = Path(path)
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise PlanError("%s: cannot read %s: %r" % (label, path, exc))
    if not isinstance(value, dict):
        raise PlanError("%s: %s is not a JSON object" % (label, path))
    return value, raw


def _resolve(base, value):
    path = Path(value)
    return path if path.is_absolute() else (Path(base) / path)


def _aggregate(entries):
    values = {name: str(entry["sha256"]).lower() for name, entry in entries.items()}
    return sha256_bytes(canonical_json(values).encode("utf-8"))


def argv_value(argv, name):
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return None


def argv_values(argv, name):
    values = []
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            values.append(argv[index + 1])
        elif item.startswith(name + "="):
            values.append(item.split("=", 1)[1])
    return values


def load_plan(path, raw=None):
    """Parse the plan from the bytes the caller already hash-verified.

    ``raw`` is mandatory in ``main``: the approved hash covers those exact
    bytes, so the executed document and the verified document are one object.
    Re-opening the path here would be a verify-then-use window.
    """
    path = Path(path).resolve()
    if raw is None:
        value, raw = read_json(path, "plan")
    else:
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise PlanError("plan: cannot parse %s: %r" % (path, exc))
        if not isinstance(value, dict):
            raise PlanError("plan: %s is not a JSON object" % path)
    if value.get("schema") != PLAN_SCHEMA:
        raise PlanError("plan.schema must be %s" % PLAN_SCHEMA)
    for key in ("job_uuid", "session", "source_hash", "package_hash", "job_dir",
                "status_path", "log_path", "sources", "package", "commands", "paths"):
        if not value.get(key):
            raise PlanError("plan.%s is required" % key)
    value["_plan_path"] = str(path)
    value["_plan_sha256"] = sha256_bytes(raw)
    value["source_hash"] = str(value["source_hash"]).lower()
    value["package_hash"] = str(value["package_hash"]).lower()
    for key in ("source_hash", "package_hash"):
        if not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise PlanError("plan.%s must be a 64-hex SHA-256" % key)
    if not str(value["session"]).strip():
        raise PlanError("plan.session must be the exact non-empty job session")
    required_sources = ("runner", "install", "deps")
    required_package = ("manifest", "contract", "lock")
    if not isinstance(value["sources"], dict):
        raise PlanError("plan.sources must be a JSON object")
    for name, entry in value["sources"].items():
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("sha256"):
            raise PlanError("plan.sources.%s must carry path and sha256" % name)
        entry["path"] = str(_resolve(path.parent, entry["path"]))
        entry["sha256"] = str(entry["sha256"]).lower()
    for name in required_sources:
        if name not in value["sources"]:
            raise PlanError("plan.sources.%s is required" % name)
    for name, entry in (value["package"] or {}).items():
        if name == "lock_pins":
            continue
        if not isinstance(entry, dict) or not entry.get("path"):
            raise PlanError("plan.package.%s must carry a path" % name)
        entry["path"] = str(_resolve(path.parent, entry["path"]))
        if entry.get("generated"):
            entry.pop("sha256", None)
        elif entry.get("sha256"):
            entry["sha256"] = str(entry["sha256"]).lower()
        else:
            raise PlanError("plan.package.%s must be generated or carry sha256" % name)
    for name in required_package:
        if name not in (value["package"] or {}):
            raise PlanError("plan.package.%s is required" % name)
    for key in ("job_dir", "status_path", "log_path"):
        value[key] = str(_resolve(path.parent, value[key]))
    for key, item in (value.get("paths") or {}).items():
        value["paths"][key] = str(_resolve(path.parent, item))
    commands = value.get("commands") or {}
    for name in ("install", "freeze", "package", "preflight", "train"):
        if name not in commands:
            raise PlanError("plan.commands.%s is required" % name)
    if not isinstance(commands["install"], list) or not all(isinstance(x, str) for x in commands["install"]):
        raise PlanError("plan.commands.install must be an argv array")
    if not isinstance(commands["freeze"], list) or not commands["freeze"]:
        raise PlanError("plan.commands.freeze must be a non-empty list of argv arrays")
    for argv in commands["freeze"]:
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise PlanError("plan.commands.freeze entries must be non-empty argv arrays")
    for name in ("package", "preflight", "train"):
        if not isinstance(commands[name], list) or not all(isinstance(x, str) for x in commands[name]):
            raise PlanError("plan.commands.%s must be an argv array" % name)
    for name in ("guard", "gate", "derive_contract"):
        if name in commands:
            if not isinstance(commands[name], list) or not commands[name] or not all(isinstance(x, str) for x in commands[name]):
                raise PlanError("plan.commands.%s must be a non-empty argv array" % name)
    required_paths = ("preflight_report", "approval", "runtime_freeze_json",
                      "runtime_freeze_txt", "package_check", "run_report",
                      "events", "failure", "download_manifest", "lora_dir",
                      "merged_dir", "checkpoints_dir", "gguf_zip")
    for key in required_paths:
        if not (value.get("paths") or {}).get(key):
            raise PlanError("plan.paths.%s is required" % key)
    train_argv = commands["train"]
    for flag, target in (
        ("--manifest", value["package"]["manifest"]["path"]),
        ("--contract", value["package"]["contract"]["path"]),
        ("--preflight-report", value["paths"]["preflight_report"]),
        ("--approval", value["paths"]["approval"]),
    ):
        supplied_values = argv_values(train_argv, flag)
        if not supplied_values:
            raise PlanError("plan.commands.train must pass %s" % flag)
        if len(supplied_values) > 1:
            raise PlanError("plan.commands.train must pass %s exactly once" % flag)
        supplied = supplied_values[0]
        if str(_resolve(path.parent, supplied).resolve()) != str(Path(target).resolve()):
            raise PlanError("plan.commands.train %s does not match the plan path" % flag)
    value["paths"].setdefault("approval_request", str(Path(value["job_dir"]) / "approval-request.json"))
    value["heartbeat_seconds"] = float(value.get("heartbeat_seconds") or 15.0)
    value["approval_poll_seconds"] = float(value.get("approval_poll_seconds") or 5.0)
    value["chunk_size_bytes"] = int(value.get("chunk_size_bytes") or DEFAULT_CHUNK_BYTES)
    if value["heartbeat_seconds"] <= 0 or value["approval_poll_seconds"] <= 0 or value["chunk_size_bytes"] <= 0:
        raise PlanError("heartbeat, poll, and chunk values must be positive")
    return value


def closure(plan):
    facts = {}
    source_entries = dict(plan["sources"])
    package_entries = {name: entry for name, entry in plan["package"].items()
                       if name != "lock_pins" and not entry.get("generated")}
    for group, entries in (("sources", source_entries), ("package", package_entries)):
        for name, entry in entries.items():
            path = Path(entry["path"])
            if not path.is_file():
                raise PlanError("%s.%s is missing: %s" % (group, name, path))
            actual = sha256_file(path)
            if actual != entry["sha256"]:
                raise PlanError("%s.%s changed: expected %s, found %s"
                                % (group, name, entry["sha256"], actual))
            facts[group + "_" + name] = actual
    facts["source_closure"] = _aggregate(source_entries)
    facts["package_closure"] = _aggregate(package_entries)
    lock = plan["package"].get("lock")
    pins = plan["package"].get("lock_pins")
    if lock and pins is not None:
        count = 0
        for line in Path(lock["path"]).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "==" in line:
                count += 1
        if count != int(pins):
            raise PlanError("package.lock has %d pins, expected %d" % (count, int(pins)))
    driver = Path(__file__).resolve()
    actual_driver = sha256_file(driver)
    if plan["source_hash"] != actual_driver:
        raise PlanError("plan.source_hash is the driver SHA; expected %s, found %s"
                        % (actual_driver, plan["source_hash"]))
    facts["driver_sha256"] = actual_driver
    facts["package_hash"] = plan["package_hash"]
    return facts


class Issues:
    def __init__(self):
        self.failures = []

    @property
    def ok(self):
        return not self.failures

    def fail(self, code, detail):
        self.failures.append({"code": code, "detail": detail})


class Status:
    def __init__(self, path, base, interval):
        self.path = Path(path)
        self.interval = float(interval)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._data = dict(base)
        self._data["schema"] = STATUS_SCHEMA
        self._data["heartbeat_at"] = time.time()
        self._data["updated_at"] = utc_now()
        self._write()

    def _write(self):
        atomic_write_json(self.path, self._data)

    def update(self, **fields):
        with self._lock:
            self._data.update(fields)
            self._data["heartbeat_at"] = time.time()
            self._data["updated_at"] = utc_now()
            self._write()

    def start(self):
        self._thread = threading.Thread(target=self._beat, name="status-heartbeat", daemon=True)
        self._thread.start()

    def _beat(self):
        while not self._stop.wait(self.interval):
            with self._lock:
                self._data["heartbeat_at"] = time.time()
                self._data["updated_at"] = utc_now()
                self._write()

    def terminal(self, state, **fields):
        if state not in ("complete", "failed"):
            raise ValueError("not terminal: %s" % state)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with self._lock:
            self._data.update(fields)
            self._data.update({"state": state, "terminal": True,
                               "finished_at": utc_now(), "heartbeat_at": time.time(),
                               "updated_at": utc_now()})
            self._write()


def claim_attempt(job_dir, record):
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    marker = job_dir / "attempt.marker"
    try:
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    try:
        os.write(fd, (json.dumps(record, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return marker


def attach_report(marker, status_path, job_uuid, source_hash, package_hash):
    if not marker.exists():
        print(json.dumps({"status": "no_marker", "marker": str(marker)}))
        return 3
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "bad_marker", "error": repr(exc)}))
        return 2
    if marker_data.get("job_uuid") != job_uuid:
        print(json.dumps({"status": "job_uuid_mismatch", "marker": marker_data.get("job_uuid"),
                          "plan": job_uuid}))
        return 2
    if marker_data.get("source_hash") != source_hash or marker_data.get("package_hash") != package_hash:
        print(json.dumps({"status": "identity_mismatch", "marker": marker_data,
                          "plan_source": source_hash, "plan_package": package_hash}))
        return 2
    state = "unknown"
    if Path(status_path).exists():
        try:
            state = json.loads(Path(status_path).read_text(encoding="utf-8")).get("state", "unknown")
        except Exception:
            state = "unknown"
    print(json.dumps({"status": "attached", "marker": str(marker), "state": state,
                      "job_uuid": job_uuid, "note": "no optimizer step will run again"}))
    if state == "complete":
        return 0
    if state == "failed":
        return 1
    return 3


def run_stage(status, log, stage, state, phase, argv):
    status.update(state=state, phase=phase, stage=stage, child_exit_code=None)
    log.write("[%s] START %s: %s\n" % (utc_now(), stage, json.dumps(argv)))
    log.flush()
    started = time.time()
    try:
        completed = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=False)
    except FileNotFoundError as exc:
        raise StageError(stage, "command not found: %r" % (exc,), 127)
    elapsed = round(time.time() - started, 3)
    log.write("[%s] END %s rc=%s seconds=%s\n" % (utc_now(), stage, completed.returncode, elapsed))
    log.flush()
    status.update(child_exit_code=int(completed.returncode), stage_seconds=elapsed)
    return int(completed.returncode)


def _flag(argv, name):
    return argv_value(argv, name)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise StageError("approval", "cannot import runner %s" % path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_approval_with_runner(plan, report, report_bytes, approval, approval_bytes):
    runner_path = Path(plan["sources"]["runner"]["path"])
    if sha256_file(runner_path) != plan["sources"]["runner"]["sha256"]:
        raise StageError("approval", "runner changed before approval check")
    module = load_module(runner_path, "_reviewed_job_runner")
    if not all(hasattr(module, name) for name in ("load_package", "new_issues", "verify_approval")):
        raise StageError("approval", "runner does not expose load_package/new_issues/verify_approval")
    train_argv = plan["commands"]["train"]
    manifest = _flag(train_argv, "--manifest") or plan["package"]["manifest"]["path"]
    contract = _flag(train_argv, "--contract") or plan["package"]["contract"]["path"]
    kwargs = {}
    for flag, key in (("--dataset", "dataset"), ("--ledger", "ledger"), ("--audit", "audit"),
                      ("--validation", "validation"), ("--deps", "deps"), ("--review", "review")):
        value = _flag(train_argv, flag)
        if value:
            kwargs[key] = value
    package = module.load_package(manifest, contract, **kwargs)
    if not getattr(package.issues, "ok", False):
        raise StageError("approval", "package refused: %s" % json.dumps(package.issues.failures))
    issues = module.new_issues()
    module.verify_approval(approval, approval_bytes, report, report_bytes, package, issues)
    if not getattr(issues, "ok", False):
        raise StageError("approval", "runner verify_approval refused: %s" % json.dumps(issues.failures))
    return {"manifest": package.manifest_sha256, "contract": package.contract_sha256}


def _read_status_file(path, label):
    try:
        value, raw = read_json(path, label)
    except PlanError as exc:
        raise StageError(label, str(exc))
    if value.get("status") != "pass":
        raise StageError(label, "%s is not a passing report" % label)
    return value, raw


def await_approval(plan, status, log):
    report_path = Path(plan["paths"]["preflight_report"])
    report, report_bytes = _read_status_file(report_path, "preflight_report")
    freeze_json = Path(plan["paths"]["runtime_freeze_json"])
    freeze_txt = Path(plan["paths"]["runtime_freeze_txt"])
    if not freeze_json.is_file() or not freeze_txt.is_file():
        raise StageError("preflight", "runtime freeze report or lock snapshot is missing")
    log.write("[%s] AWAITING parent approval at %s\n"
              % (utc_now(), plan["paths"]["approval"]))
    log.flush()
    # Hand off a sealed copy: the live job.log keeps growing after approval.
    snapshot_path = Path(plan["job_dir"]) / "handoff" / Path(plan["log_path"]).name
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_bytes = Path(plan["log_path"]).read_bytes()
    with snapshot_path.open("wb") as handle:
        handle.write(snapshot_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    snapshot_sha256 = sha256_bytes(snapshot_bytes)
    report_paths = [str(report_path), str(freeze_json), str(freeze_txt)]
    hashes = {str(path): sha256_file(path) for path in (report_path, freeze_json, freeze_txt)}
    hashes[str(snapshot_path)] = snapshot_sha256
    used = set()
    handoff = [
        (report_path, "report", "json", "preflight_report", "preflight-report.json"),
        (freeze_json, "report", "json", "runtime_freeze", "runtime-freeze.json"),
        (freeze_txt, "report", "txt", "runtime_freeze_lock", "runtime-freeze.txt"),
        (snapshot_path, "log", "text", "job_log", Path(plan["log_path"]).name),
    ]
    handoff_artifacts = []
    for path, kind, fmt, label, name in handoff:
        digest = hashes[str(path)]
        handoff_artifacts.append({
            "path": str(path), "bytes": path.stat().st_size, "sha256": digest,
            "kind": kind, "role": kind, "format": fmt, "label": label,
            "local_name": _safe_local(name, used), "required": True,
            "original_name": name, "archive_sha256": digest,
            "chunk_index": 1, "chunk_count": 1,
        })
    approval_path = Path(plan["paths"]["approval"])
    request_path = Path(plan["paths"]["approval_request"])
    contract, _ = read_json(plan["package"]["contract"]["path"], "contract")
    request = {
        "schema": APPROVAL_REQUEST_SCHEMA,
        "not_an_approval": True,
        "job_uuid": plan["job_uuid"],
        "session": plan["session"],
        "manifest_sha256": sha256_file(plan["package"]["manifest"]["path"]),
        "contract_sha256": sha256_file(plan["package"]["contract"]["path"]),
        "preflight_report_sha256": sha256_bytes(report_bytes),
        "export": contract.get("export"),
        "approval_path": str(approval_path),
    }
    atomic_write_json(request_path, request)
    status.update(state="preflight", phase="awaiting_approval",
                  report_paths=report_paths, artifact_hashes=hashes,
                  artifacts=handoff_artifacts,
                  report_artifact_paths=[str(report_path), str(freeze_json), str(freeze_txt)],
                  log_artifact_paths=[str(snapshot_path)],
                  log_snapshot_path=str(snapshot_path),
                  log_snapshot_sha256=snapshot_sha256,
                  preflight_report_sha256=sha256_bytes(report_bytes),
                  approval_path=str(approval_path), approval_request_path=str(request_path))
    while not approval_path.is_file():
        time.sleep(plan["approval_poll_seconds"])
    approval_bytes = approval_path.read_bytes()
    try:
        approval = json.loads(approval_bytes.decode("utf-8"))
    except Exception as exc:
        raise StageError("approval", "approval is not valid JSON: %r" % (exc,))
    if not isinstance(approval, dict):
        raise StageError("approval", "approval is not a JSON object")
    verify_approval_with_runner(plan, report, report_bytes, approval, approval_bytes)
    status.update(approval_sha256=sha256_bytes(approval_bytes),
                  phase="approval_verified")
    return sha256_bytes(approval_bytes)


def _zip_dir(src, dest):
    src = Path(src)
    dest = Path(dest)
    files = [path for path in src.rglob("*") if path.is_file()]
    if not files:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(src.parent).as_posix())
    return True


def _chunks(path, chunk_size, chunks_dir, local_name=None):
    path = Path(path)
    base = local_name or path.name
    size = path.stat().st_size
    if size <= chunk_size:
        return [{"path": str(path), "bytes": size, "sha256": sha256_file(path),
                 "local_name": base}]
    chunks_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    with path.open("rb") as handle:
        index = 1
        while True:
            data = handle.read(chunk_size)
            if not data:
                break
            part = chunks_dir / ("%s.part%03d" % (base, index))
            part.write_bytes(data)
            parts.append({"path": str(part), "bytes": len(data),
                          "sha256": sha256_bytes(data),
                          "local_name": part.name})
            index += 1
    return parts


def _logical(name, kind, role, fmt, label, path, chunk_size, chunks_dir):
    path = Path(path)
    archive_sha = sha256_file(path)
    return {"name": name, "original_name": name, "kind": kind, "role": role,
            "format": fmt, "label": label, "bytes": path.stat().st_size,
            "sha256": archive_sha, "archive_sha256": archive_sha,
            "chunks": _chunks(path, chunk_size, chunks_dir, name)}


def _safe_local(name, used):
    base = Path(str(name)).name.replace("\\", "__").replace("/", "__")
    base = base.replace("..", "__").strip()
    if not base or base in (".", "/"):
        base = "artifact"
    stem, suffix = Path(base).stem, "".join(Path(base).suffixes)
    candidate = base
    index = 2
    while candidate in used:
        candidate = "%s-%d%s" % (stem, index, suffix)
        index += 1
    used.add(candidate)
    return candidate


def required_missing(plan):
    paths = plan["paths"]
    missing = []

    def has_file(key):
        if not Path(paths[key]).is_file():
            missing.append(key)

    def has_dir(key):
        directory = Path(paths[key])
        if not directory.is_dir() or not any(path.is_file() for path in directory.rglob("*")):
            missing.append(key)

    has_dir("lora_dir")
    has_dir("merged_dir")
    has_file("gguf_zip")
    has_file("run_report")
    has_file("preflight_report")
    has_file("runtime_freeze_json")
    has_file("runtime_freeze_txt")
    has_file("package_check")
    has_file("events")
    return missing


def _stage_index(stage):
    try:
        return STAGE_SEQUENCE.index(str(stage))
    except ValueError:
        return None


def expected_absent_reason(key, failure_stage, stage_failed):
    """Why a plan-path artifact was never produced, or None if it should exist.

    A report that is written only when its stage succeeds (preflight, run) is
    expected to be absent when that stage failed. Everything else is a real
    gap and stays in ``missing``.
    """
    produced = PLAN_ARTIFACT_STAGES.get(key)
    if produced is None or not failure_stage:
        return None
    index = _stage_index(failure_stage)
    if index is None:
        return None
    produced_index = _stage_index(produced)
    if index < produced_index:
        return "stage %s failed before %s ran" % (failure_stage, produced)
    if index == produced_index and stage_failed:
        return "stage %s failed without writing %s" % (failure_stage, key)
    return None


def _diagnostic_candidates(plan):
    """Every runner-side evidence file the driver knows how to look for.

    Paths follow the runner's own output directories, derived from the plan's
    report paths. ``applies_at`` names the one stage that writes a failure
    record.
    """
    paths = plan["paths"]
    preflight_out = Path(paths["preflight_report"]).parent
    train_out = Path(paths["run_report"]).parent

    def candidate(label, path, name, local_name, kind, role, stage, fmt,
                  produced_at, applies_at=None, plan_key=None):
        return {"label": label, "plan_key": plan_key, "path": Path(path),
                "name": name, "local_name": local_name, "kind": kind,
                "role": role, "stage": stage, "format": fmt,
                "produced_at": produced_at, "applies_at": applies_at}

    return (
        candidate("package_check", paths["package_check"], "package-check.json",
                  "package-check.json", "report", "report", "package", "json",
                  "package", plan_key="package_check"),
        candidate("runtime_freeze_json", paths["runtime_freeze_json"],
                  "runtime-freeze.json", "runtime-freeze.json", "report",
                  "report", "runtime_freeze", "json", "runtime_freeze",
                  plan_key="runtime_freeze_json"),
        candidate("runtime_freeze_txt", paths["runtime_freeze_txt"],
                  "runtime-freeze.txt", "runtime-freeze.txt", "report",
                  "report", "runtime_freeze", "txt", "runtime_freeze",
                  plan_key="runtime_freeze_txt"),
        candidate("preflight_report", paths["preflight_report"],
                  "preflight-report.json", "preflight-report.json", "report",
                  "report", "preflight", "json", "preflight",
                  plan_key="preflight_report"),
        candidate("preflight_runner_failure",
                  preflight_out / "preflight-failure.json",
                  "preflight-failure.json", "preflight-failure.json", "report",
                  "runner_failure", "preflight", "json", "preflight",
                  applies_at="preflight"),
        candidate("preflight_events", preflight_out / "events.jsonl",
                  "events.jsonl", "preflight-events.jsonl", "log", "stage_events",
                  "preflight", "jsonl", "preflight"),
        candidate("identity_measurement_preflight",
                  preflight_out / "identity-measurement.json",
                  "identity-measurement.json",
                  "preflight-identity-measurement.json", "report",
                  "identity_measurement", "preflight", "json", "preflight"),
        candidate("run_report", paths["run_report"], "training-run-report.json",
                  "training-run-report.json", "report", "report", "train",
                  "json", "train", plan_key="run_report"),
        candidate("train_runner_failure", train_out / "run-failure.json",
                  "run-failure.json", "train-run-failure.json", "report",
                  "runner_failure", "train", "json", "train",
                  applies_at="train"),
        candidate("train_events", train_out / "events.jsonl", "events.jsonl",
                  "train-events.jsonl", "log", "stage_events", "train",
                  "jsonl", "train"),
        candidate("identity_measurement_train",
                  train_out / "identity-measurement.json",
                  "identity-measurement.json",
                  "train-identity-measurement.json", "report",
                  "identity_measurement", "train", "json", "train"),
    )


def _diagnostic_absence(candidate, failure_stage, stage_failed):
    name = candidate["name"]
    index = _stage_index(failure_stage) if failure_stage else None
    produced_index = _stage_index(candidate["produced_at"])
    if index is None or produced_index is None:
        return "missing", "failure stage is unknown; %s was not found" % name
    applies_at = candidate.get("applies_at")
    if applies_at:
        if index < produced_index:
            return "expected_absent", "stage %s failed before %s ran" % (
                failure_stage, candidate["stage"])
        if index != _stage_index(applies_at):
            return "expected_absent", "%s is only written when %s fails; failed stage is %s" % (
                name, applies_at, failure_stage)
    if index < produced_index:
        return "expected_absent", "stage %s failed before %s ran" % (
            failure_stage, candidate["stage"])
    if index == produced_index:
        if stage_failed:
            return "expected_absent", "stage %s failed without creating %s" % (
                failure_stage, name)
        return "missing", "stage %s succeeded but %s is absent" % (
            failure_stage, name)
    return "missing", "stage %s completed earlier but %s is absent" % (
        candidate["stage"], name)


def collect_diagnostics(plan, failure_stage=None, stage_failed=True):
    """Hash every available runner diagnostic; classify every absent one.

    Files are read where the runner writes them (preflight-out and train-out,
    both derived from the plan's report paths). Nothing is copied or invented:
    a present file carries its real size and SHA-256, an absent file carries
    ``expected_absent`` only when the failed stage accounts for its absence.
    """
    entries = []
    for candidate in _diagnostic_candidates(plan):
        path = Path(candidate["path"])
        entry = {key: candidate[key] for key in
                 ("label", "plan_key", "name", "local_name", "kind", "role",
                  "stage", "format")}
        entry["path"] = str(path)
        if path.is_file():
            digest = sha256_file(path)
            entry.update(status="present", sha256=digest,
                         archive_sha256=digest, bytes=path.stat().st_size)
        else:
            status, reason = _diagnostic_absence(candidate, failure_stage,
                                                 stage_failed)
            entry.update(status=status, reason=reason)
        entries.append(entry)
    return entries


def collect_failure_diagnostics(plan, log, failure_stage, stage_failed):
    """Never let a diagnostic read failure hide the stage failure itself."""
    try:
        return collect_diagnostics(plan, failure_stage, stage_failed), None
    except Exception as exc:
        log.write("[%s] diagnostics collection failed: %r\n" % (utc_now(), exc))
        log.flush()
        return [], repr(exc)


def package_outputs(plan, status, log, complete, failure_stage=None,
                    stage_failed=True, diagnostics=None):
    paths = plan["paths"]
    job_dir = Path(plan["job_dir"])
    pack_dir = job_dir / "pack"
    chunks_dir = pack_dir / "chunks"
    pack_dir.mkdir(parents=True, exist_ok=True)
    logical = []
    missing = []
    expected_absent = []
    classified = set()
    published = set()

    def note_absent(key, name, path, reason, absent):
        resolved = str(Path(path).resolve())
        if resolved in classified:
            return
        classified.add(resolved)
        if absent:
            expected_absent.append({"key": key, "name": name, "path": str(path),
                                    "reason": reason})
        else:
            missing.append(name)

    def add_file(name, kind, role, fmt, label, path, required=False, key=None,
                 stage=None):
        path = Path(path)
        if path.is_file():
            item = _logical(name, kind, role, fmt, label, path,
                            plan["chunk_size_bytes"], chunks_dir)
            if stage:
                item["stage"] = stage
            logical.append(item)
            published.add(str(path.resolve()))
            return True
        if required:
            reason = expected_absent_reason(key, failure_stage, stage_failed) if key else None
            note_absent(key or label, name, path,
                        reason or "required artifact was not found",
                        absent=bool(reason))
        return False

    def add_dir(name, kind, role, fmt, label, directory, required=False,
                key=None, stage=None):
        directory = Path(directory)
        if directory.is_dir():
            archive = pack_dir / name
            try:
                if _zip_dir(directory, archive):
                    item = _logical(name, kind, role, fmt, label, archive,
                                    plan["chunk_size_bytes"], chunks_dir)
                    if stage:
                        item["stage"] = stage
                    logical.append(item)
                    return True
            except Exception as exc:
                log.write("[%s] zip failed %s: %r\n" % (utc_now(), directory, exc))
                log.flush()
                for path in sorted(directory.rglob("*")):
                    if path.is_file():
                        raw_name = (directory.name + "__" + path.relative_to(directory).as_posix())
                        raw_name = raw_name.replace("/", "__")
                        item = _logical(raw_name, kind, role, fmt, label, path,
                                        plan["chunk_size_bytes"], chunks_dir)
                        if stage:
                            item["stage"] = stage
                        logical.append(item)
                return True
        if required:
            reason = expected_absent_reason(key, failure_stage, stage_failed) if key else None
            note_absent(key or label, name, directory,
                        reason or "required artifact was not found",
                        absent=bool(reason))
        return False

    add_dir("lora.zip", "model", "model", "safetensors", "adapter",
            paths["lora_dir"], required=complete, key="lora_dir", stage="train")
    add_dir("merged_16bit.zip", "model", "model", "safetensors", "merged",
            paths["merged_dir"], required=complete, key="merged_dir", stage="train")
    if not complete:
        add_dir("checkpoints.zip", "model", "model", "safetensors", "checkpoint",
                paths["checkpoints_dir"], required=False, stage="train")
    add_file("gguf.zip", "model", "model", "gguf", "gguf",
             paths["gguf_zip"], required=complete, key="gguf_zip", stage="train")
    add_file("training-run-report.json", "report", "report", "json", "run_report",
             paths["run_report"], required=complete, key="run_report",
             stage="train")
    add_file("preflight-report.json", "report", "report", "json", "preflight_report",
             paths["preflight_report"], required=True, key="preflight_report",
             stage="preflight")
    add_file("runtime-freeze.json", "report", "report", "json", "runtime_freeze",
             paths["runtime_freeze_json"], required=True, key="runtime_freeze_json",
             stage="runtime_freeze")
    add_file("runtime-freeze.txt", "report", "report", "txt", "runtime_freeze_lock",
             paths["runtime_freeze_txt"], required=True, key="runtime_freeze_txt",
             stage="runtime_freeze")
    add_file("package-check.json", "report", "report", "json", "package_check",
             paths["package_check"], required=complete, key="package_check",
             stage="package")
    add_file("train-events.jsonl", "log", "log", "jsonl", "runner_events",
             paths["events"], required=complete, key="events", stage="train")
    add_file("job.log", "log", "log", "text", "job_log",
             plan["log_path"], required=True)
    add_file("failure.json", "report", "report", "json", "failure",
             paths["failure"], required=False, stage=failure_stage)

    for entry in diagnostics or []:
        path = Path(entry["path"])
        if entry.get("status") == "present":
            resolved = str(path.resolve())
            if resolved in published:
                continue
            item = _logical(entry["local_name"], entry["kind"], entry["role"],
                            entry["format"], entry["label"], path,
                            plan["chunk_size_bytes"], chunks_dir)
            item["stage"] = entry["stage"]
            logical.append(item)
            published.add(resolved)
        else:
            note_absent(entry["label"], entry["local_name"], path,
                        entry.get("reason") or "artifact was not created",
                        absent=(entry.get("status") == "expected_absent"))

    used = set()
    for item in logical:
        for chunk in item["chunks"]:
            chunk["local_name"] = _safe_local(chunk["local_name"], used)

    download_path = Path(paths["download_manifest"])
    payload = {"schema": DOWNLOADS_SCHEMA, "job_uuid": plan["job_uuid"],
               "session": plan["session"], "complete": bool(complete),
               "failure_stage": failure_stage,
               "missing": missing, "expected_absent": expected_absent,
               "artifacts": logical,
               "reassembly": "concatenate each artifact's chunks in order, then verify its sha256"}
    atomic_write_json(download_path, payload)

    flat = []
    hashes = {}
    report_paths = []
    artifact_paths = []
    for item in logical:
        count = len(item["chunks"])
        for index, chunk in enumerate(item["chunks"], 1):
            fmt = "archive_chunk" if count > 1 else item["format"]
            entry = {
                "path": chunk["path"], "bytes": chunk["bytes"],
                "sha256": chunk["sha256"], "kind": item["kind"],
                "role": item["role"], "format": fmt, "label": item["label"],
                "local_name": chunk["local_name"], "required": True,
                "original_name": item["name"],
                "archive_sha256": item["sha256"],
                "chunk_index": index, "chunk_count": count,
            }
            if item.get("stage"):
                entry["stage"] = item["stage"]
            flat.append(entry)
            hashes[chunk["path"]] = chunk["sha256"]
            if item["kind"] == "report":
                report_paths.append(chunk["path"])
            elif item["kind"] == "model":
                artifact_paths.append(chunk["path"])
    if complete:
        for need in ("model", "report", "log"):
            if not any(item["kind"] == need for item in flat):
                missing.append(need + "_artifact")
    manifest_sha = sha256_file(download_path)
    hashes[str(download_path)] = manifest_sha
    report_paths.insert(0, str(download_path))
    status.update(state="export", phase="packaging",
                  artifacts=flat, artifact_paths=artifact_paths,
                  report_paths=report_paths, artifact_hashes=hashes,
                  model_artifact_paths=[item["path"] for item in flat if item["kind"] == "model"],
                  report_artifact_paths=[item["path"] for item in flat if item["kind"] == "report"],
                  log_artifact_paths=[item["path"] for item in flat if item["kind"] == "log"],
                  download_manifest=str(download_path), missing_artifacts=missing,
                  expected_absent=expected_absent, failure_stage=failure_stage)
    return missing


def write_failure(plan, stage, message, exit_code, diagnostics=None,
                  diagnostics_error=None):
    path = Path(plan["paths"]["failure"])
    present = [entry for entry in (diagnostics or [])
               if entry.get("status") == "present"]
    payload = {"schema": FAILURE_SCHEMA, "job_uuid": plan["job_uuid"],
               "session": plan["session"],
               "source_hash": plan["source_hash"],
               "package_hash": plan["package_hash"],
               "plan_sha256": plan["_plan_sha256"],
               "stage": stage, "status": "fail",
               "exit_code": int(exit_code or 1), "error": str(message),
               "log_path": plan["log_path"], "at": utc_now(),
               "diagnostics": diagnostics or [],
               "diagnostic_paths": {entry["label"]: entry["path"]
                                    for entry in present}}
    if diagnostics_error:
        payload["diagnostics_error"] = str(diagnostics_error)
    atomic_write_json(path, payload)
    return path


def _status_base(plan, facts):
    return {"job_uuid": plan["job_uuid"], "session": plan["session"],
            "source_hash": plan["source_hash"], "package_hash": plan["package_hash"],
            "pid": os.getpid(), "state": "setup", "phase": "claimed",
            "heartbeat_at": time.time(), "log_path": plan["log_path"],
            "job_dir": plan["job_dir"], "plan_sha256": plan["_plan_sha256"],
            "source_closure": facts.get("source_closure"),
            "package_closure": facts.get("package_closure"),
            "driver_sha256": facts.get("driver_sha256")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="One reviewed training attempt, OS background.")
    parser.add_argument("--plan", required=True, help="reviewed-job-plan/1 JSON")
    parser.add_argument("--plan-sha256", required=True,
                        help="caller-known SHA-256 of the exact plan bytes")
    parser.add_argument("--check-plan", action="store_true",
                        help="verify plan closure and exit without claiming an attempt")
    args = parser.parse_args(argv)
    try:
        raw_plan = Path(args.plan).read_bytes()
    except Exception as exc:
        print(json.dumps({"status": "plan_unreadable", "error": str(exc)}))
        return 2
    expected_plan = str(args.plan_sha256).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_plan):
        print(json.dumps({"status": "plan_hash_invalid",
                          "error": "--plan-sha256 must be 64 hex"}))
        return 2
    if sha256_bytes(raw_plan) != expected_plan:
        print(json.dumps({"status": "plan_hash_mismatch",
                          "expected": expected_plan,
                          "actual": sha256_bytes(raw_plan)}))
        return 2
    try:
        plan = load_plan(args.plan, raw_plan)
    except Exception as exc:
        print(json.dumps({"status": "plan_invalid", "error": str(exc)}))
        return 2
    try:
        facts = closure(plan)
    except Exception as exc:
        print(json.dumps({"status": "closure_invalid", "error": str(exc)}))
        return 2
    if args.check_plan:
        print(json.dumps({"status": "pass", "plan_sha256": plan["_plan_sha256"],
                          "source_hash": plan["source_hash"],
                          "package_hash": plan["package_hash"],
                          "source_closure": facts.get("source_closure"),
                          "package_closure": facts.get("package_closure")},
                         indent=1, sort_keys=True))
        return 0

    job_dir = Path(plan["job_dir"])
    marker = job_dir / "attempt.marker"
    record = {"job_uuid": plan["job_uuid"], "session": plan["session"],
              "source_hash": plan["source_hash"], "package_hash": plan["package_hash"],
              "plan_sha256": plan["_plan_sha256"], "created_at": utc_now()}
    claimed = claim_attempt(job_dir, record)
    if claimed is None:
        return attach_report(marker, plan["status_path"], plan["job_uuid"],
                             plan["source_hash"], plan["package_hash"])

    log = Path(plan["log_path"])
    log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log.open("a", encoding="utf-8")
    try:
        status = Status(plan["status_path"], _status_base(plan, facts),
                        plan["heartbeat_seconds"])
        status.start()
        log_handle.write("[%s] claimed %s for %s\n" % (utc_now(), marker, plan["session"]))
        log_handle.flush()
        packaged = False
        try:
            for name, phase in (("guard", "guard"), ("gate", "gate"),
                                ("derive_contract", "derive_contract")):
                command = plan["commands"].get(name)
                if command:
                    rc = run_stage(status, log_handle, name, "setup", phase, command)
                    if rc != 0:
                        raise StageError(name, "%s exited %d" % (name, rc), rc)
                    if name == "gate" and not Path(plan["package"]["manifest"]["path"]).is_file():
                        raise StageError("gate", "gate did not write the manifest",
                                         1, stage_failed=False)
                    if name == "derive_contract":
                        if not Path(plan["package"]["contract"]["path"]).is_file():
                            raise StageError("derive_contract",
                                             "contract was not written", 1,
                                             stage_failed=False)
                        status.update(generated_manifest_sha256=sha256_file(
                            plan["package"]["manifest"]["path"]))
                        status.update(generated_contract_sha256=sha256_file(
                            plan["package"]["contract"]["path"]))
            rc = run_stage(status, log_handle, "package", "setup", "package_check",
                           plan["commands"]["package"])
            if rc != 0:
                raise StageError("package", "package check exited %d" % rc, rc)
            try:
                _read_status_file(plan["paths"]["package_check"], "package_check")
            except StageError as exc:
                raise StageError("package", str(exc), exc.exit_code,
                                 stage_failed=False)
            rc = run_stage(status, log_handle, "install", "setup", "install",
                           plan["commands"]["install"])
            if rc != 0:
                raise StageError("install", "install exited %d" % rc, rc)
            for index, command in enumerate(plan["commands"]["freeze"]):
                rc = run_stage(status, log_handle, "runtime_freeze_%d" % index,
                               "setup", "runtime_freeze", command)
                if rc != 0:
                    raise StageError("runtime_freeze", "freeze check exited %d" % rc, rc)
            for key in ("runtime_freeze_json", "runtime_freeze_txt"):
                if not Path(plan["paths"][key]).is_file():
                    raise StageError("runtime_freeze", "%s was not written" % key,
                                     1, stage_failed=False)
            rc = run_stage(status, log_handle, "preflight", "preflight", "preflight",
                           plan["commands"]["preflight"])
            if rc != 0:
                raise StageError("preflight", "preflight exited %d" % rc, rc)
            try:
                _read_status_file(plan["paths"]["preflight_report"],
                                  "preflight_report")
            except StageError as exc:
                raise StageError("preflight", str(exc), exc.exit_code,
                                 stage_failed=False)
            await_approval(plan, status, log_handle)
            rc = run_stage(status, log_handle, "train", "training", "train",
                           plan["commands"]["train"])
            if rc != 0:
                raise StageError("train", "train exited %d" % rc, rc)
            missing = required_missing(plan)
            if missing:
                diagnostics, diagnostics_error = collect_failure_diagnostics(
                    plan, log_handle, "export", False)
                failure = write_failure(plan, "export", "missing required artifacts: %s"
                                        % json.dumps(missing), 1,
                                        diagnostics=diagnostics,
                                        diagnostics_error=diagnostics_error)
                log_handle.write("[%s] FAILED export: missing %s\n"
                                 % (utc_now(), json.dumps(missing)))
                log_handle.flush()
                package_outputs(plan, status, log_handle, complete=False,
                                failure_stage="export", stage_failed=False,
                                diagnostics=diagnostics)
                packaged = True
                status.terminal("failed", phase="failed", child_exit_code=0,
                                exit_code=1, failure_path=str(failure),
                                stdout_path=plan["log_path"], packaged=True)
                return 1
            log_handle.write("[%s] TRAIN FINISHED; PACKAGING\n" % utc_now())
            log_handle.flush()
            package_outputs(plan, status, log_handle, complete=True)
            packaged = True
            status.terminal("complete", phase="complete", child_exit_code=0,
                            exit_code=0, artifacts_complete=True)
            return 0
        except StageError as exc:
            diagnostics, diagnostics_error = collect_failure_diagnostics(
                plan, log_handle, exc.stage, exc.stage_failed)
            failure = write_failure(plan, exc.stage, exc.message, exc.exit_code,
                                    diagnostics=diagnostics,
                                    diagnostics_error=diagnostics_error)
            log_handle.write("[%s] FAILED %s: %s\n" % (utc_now(), exc.stage, exc.message))
            log_handle.flush()
            if not packaged:
                try:
                    package_outputs(plan, status, log_handle, complete=False,
                                    failure_stage=exc.stage,
                                    stage_failed=exc.stage_failed,
                                    diagnostics=diagnostics)
                    packaged = True
                except Exception as package_exc:
                    log_handle.write("[%s] salvage packaging failed: %r\n" % (utc_now(), package_exc))
                    log_handle.flush()
            status.terminal("failed", phase="failed", child_exit_code=exc.exit_code,
                            exit_code=exc.exit_code, failure_path=str(failure),
                            stdout_path=plan["log_path"], packaged=packaged)
            return 1
        except Exception as exc:
            diagnostics, diagnostics_error = collect_failure_diagnostics(
                plan, log_handle, None, False)
            failure = write_failure(plan, "driver", repr(exc), 1,
                                    diagnostics=diagnostics,
                                    diagnostics_error=diagnostics_error)
            log_handle.write("[%s] FAILED driver: %r\n" % (utc_now(), exc))
            log_handle.flush()
            if not packaged:
                try:
                    package_outputs(plan, status, log_handle, complete=False,
                                    failure_stage=None, stage_failed=False,
                                    diagnostics=diagnostics)
                    packaged = True
                except Exception as package_exc:
                    log_handle.write("[%s] salvage packaging failed: %r\n" % (utc_now(), package_exc))
                    log_handle.flush()
            status.terminal("failed", phase="failed", child_exit_code=1, exit_code=1,
                            failure_path=str(failure), stdout_path=plan["log_path"],
                            packaged=packaged)
            return 1
    finally:
        log_handle.close()


if __name__ == "__main__":
    sys.exit(main())
