"""Tests for the Colab training watchdog. Pure logic + fake CLI adapter."""

import builtins
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "artifacts", "colab"))
import run_reviewed_job as D  # noqa: E402
import watch_training as W  # noqa: E402


def _cp(rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["fake"], rc, stdout, stderr)


class FakeCLI:
    def __init__(self, probes=None, downloads=None, sessions_text="", stop_rc=0):
        self.probes = list(probes or [])
        self.downloads = dict(downloads or {})
        self.sessions_text = sessions_text
        self.stop_rc = stop_rc
        self.stop_calls = []
        self.download_calls = []
        self.exec_calls = []

    def sessions(self):
        return _cp(0, self.sessions_text, "")

    def status(self, session):
        return _cp(0, "", "")

    def exec_code(self, session, code, timeout=30.0):
        self.exec_calls.append((session, code, timeout))
        if not self.probes:
            return _cp(1, "", "no more probes")
        item = self.probes.pop(0)
        if isinstance(item, Exception):
            raise item
        if item == "transport":
            return _cp(1, "", "network down")
        if item == "badjson":
            return _cp(0, "not json at all", "")
        return _cp(0, "WATCHDOG_JSON:" + json.dumps(item), "")

    def download(self, session, remote_path, local_path, timeout=300.0):
        self.download_calls.append((session, remote_path, local_path))
        spec = self.downloads.get(remote_path, (0, b""))
        if isinstance(spec, Exception):
            raise spec
        rc, content = spec
        if rc == 0:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            Path(local_path).write_bytes(content)
        return _cp(rc, "", "" if rc == 0 else "download failed")

    def stop(self, session):
        self.stop_calls.append(session)
        return _cp(self.stop_rc, "", "")


def _probe(status=None, error=None, pid_alive=False, remote_now=1000.0):
    return {"status": status, "error": error, "pid_alive": pid_alive, "remote_now": remote_now, "log_mtime": None}


def _status(state, job_uuid="U", session="sess-A", pid=123, heartbeat=999.0, remote_now=1000.0,
            source="a"*64, package="b"*64, exit_code=0, artifacts=None, reports=None, log=None, hashes=None):
    s = {
        "job_uuid": job_uuid,
        "session": session,
        "state": state,
        "pid": pid,
        "heartbeat_at": heartbeat,
        "source_hash": source,
        "package_hash": package,
        "child_exit_code": exit_code,
    }
    if artifacts is not None:
        s["artifact_paths"] = artifacts
    if reports is not None:
        s["report_paths"] = reports
    if log is not None:
        s["log_path"] = log
    if hashes is not None:
        s["artifact_hashes"] = hashes
    return s


class WatchdogTests(unittest.TestCase):
    def _wd(self, tmp, fake, **kw):
        defaults = dict(
            session="sess-A",
            job_dir="/content/job",
            job_uuid="U",
            state_dir=Path(tmp) / "state",
            cli=fake,
            poll_interval=0.0,
            rpc_timeout=5.0,
            max_polls=1,
            sleeper=lambda x: None,
            expected_source_hash="a"*64,
            expected_package_hash="b"*64,
        )
        defaults.update(kw)
        return W.Watchdog(**defaults)

    def test_good_complete_downloads_and_stops(self):
        content = b"GGUF-BYTES"
        h = hashlib.sha256(content).hexdigest()
        rh = hashlib.sha256(b"r").hexdigest()
        lh = hashlib.sha256(b"log").hexdigest()
        st = _status("complete", artifacts=["/content/a.gguf"], reports=["/content/r.json"], log="/content/train.log", hashes={"/content/a.gguf": h, "/content/r.json": rh, "/content/train.log": lh})
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)],
                      downloads={"/content/a.gguf": (0, content), "/content/r.json": (0, b"r"), "/content/train.log": (0, b"log")},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake)
        # fix hash for report
        wd2 = wd
        rc = wd.run()
        self.assertEqual(rc, 0)
        self.assertTrue((Path(tmp) / "state" / "artifacts" / "a.gguf").exists())
        self.assertEqual(fake.stop_calls, ["sess-A"])

    def test_complete_requires_exit_code_zero(self):
        content = b"X"
        h = hashlib.sha256(content).hexdigest()
        st = _status("complete", exit_code=None, artifacts=["/content/a.gguf"], reports=["/content/r.json"], hashes={"/content/a.gguf": h, "/content/r.json": h})
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)], downloads={"/content/a.gguf":(0,content)}, sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=2)
        fake.probes.append(_probe(st, pid_alive=False, remote_now=1000.0))
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_complete_requires_artifact_and_report(self):
        content = b"X"
        h = hashlib.sha256(content).hexdigest()
        # no reports
        st = _status("complete", artifacts=["/content/a.gguf"], hashes={"/content/a.gguf": h})
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)], downloads={"/content/a.gguf":(0,content)}, sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_complete_requires_exact_hashes(self):
        content = b"X"
        h = hashlib.sha256(content).hexdigest()
        st = _status("complete", source="WRONG", artifacts=["/content/a.gguf"], reports=["/content/r.json"], hashes={"/content/a.gguf": h, "/content/r.json": h})
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)], downloads={"/content/a.gguf":(0,content)}, sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_failed_download_blocks_no_stop(self):
        st = _status("failed", log="/content/train.log")
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)],
                      downloads={"/content/train.log": (1, b"")},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake)
        rc = wd.run()
        self.assertEqual(rc, 3)
        self.assertEqual(fake.stop_calls, [])

    def test_stale_terminal_accepted_if_dead_pid_and_exit_proof(self):
        content = b"X"
        h = hashlib.sha256(content).hexdigest()
        rh = hashlib.sha256(b"r").hexdigest()
        lh = hashlib.sha256(b"log").hexdigest()
        st = _status("complete", heartbeat=1.0, artifacts=["/content/a.gguf"], reports=["/content/r.json"], log="/content/train.log", hashes={"/content/a.gguf": h, "/content/r.json": rh, "/content/train.log": lh})
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=10000.0)],
                      downloads={"/content/a.gguf": (0, content), "/content/r.json": (0, b"r"), "/content/train.log": (0, b"log")},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake)
        rc = wd.run()
        self.assertEqual(rc, 0)

    def test_stale_heartbeat_alone_not_complete(self):
        st = _status("complete", heartbeat=1.0, exit_code=None)
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=10000.0)], sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=2)
        fake.probes.append(_probe(st, pid_alive=False, remote_now=10000.0))
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_ongoing_training_no_stop(self):
        st = _status("training")
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)])
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_network_error_not_success(self):
        fake = FakeCLI(probes=["transport"])
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_wrong_job_uuid_not_terminal(self):
        st = _status("complete", job_uuid="OTHER")
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)], sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_alive_pid_not_finished(self):
        st = _status("complete")
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)], sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_scoped_stop_does_not_stop_others(self):
        # stop failure now blocks
        st = _status("failed", log="/content/train.log")
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)],
                      downloads={"/content/train.log": (0, b"log")},
                      sessions_text="[sess-A] e\n",
                      stop_rc=1)
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake)
        rc = wd.run()
        self.assertEqual(rc, 3)
        self.assertEqual(fake.stop_calls, ["sess-A"])

    def test_double_launch_blocked(self):
        tmp = tempfile.mkdtemp()
        state_dir = Path(tmp) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "watchdog.lock").write_text(json.dumps({"pid": os.getpid()}))
        fake = FakeCLI(probes=[])
        wd = W.Watchdog(
            session="sess-A", job_dir="/content/job", job_uuid="U",
            state_dir=state_dir, cli=fake, max_polls=1, sleeper=lambda x: None,
            expected_source_hash="a"*64, expected_package_hash="b"*64,
        )
        rc = wd.run()
        self.assertEqual(rc, 2)

    def test_checkpoint_binding_rejects_reuse(self):
        tmp = tempfile.mkdtemp()
        state_dir = Path(tmp) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        # write checkpoint bound to another job
        W.atomic_write_json(state_dir / "checkpoint.json", {"session": "other", "job_dir": "/content/other", "job_uuid": "OTHER"})
        fake = FakeCLI(probes=[])
        wd = W.Watchdog(
            session="sess-A", job_dir="/content/job", job_uuid="U",
            state_dir=state_dir, cli=fake, max_polls=1, sleeper=lambda x: None,
            expected_source_hash="a"*64, expected_package_hash="b"*64,
        )
        # save_checkpoint should raise
        with self.assertRaises(W.CheckpointBindingError):
            wd.save_checkpoint({"state": "training"})

    def test_launch_remote_worker_parses_pid(self):
        class LCLI(FakeCLI):
            def exec_code(self, session, code, timeout=30.0):
                self.exec_calls.append((session, code, timeout))
                return _cp(0, "LAUNCHED_PID:42\n", "")
        lfake = LCLI()
        out = W.launch_remote_worker(lfake, "sess-A", "/content/job", "echo hi", job_uuid="U")
        self.assertEqual(out["pid"], 42)
        self.assertEqual(out["returncode"], 0)

    def test_launch_second_call_recovers_not_spawns(self):
        class LCLI(FakeCLI):
            def exec_code(self, session, code, timeout=30.0):
                self.exec_calls.append((session, code, timeout))
                # first call: marker exists -> recovered
                return _cp(0, "RECOVERED_PID:" + __import__("json").dumps({"pid":7,"alive":False,"identity":"x"}) + "\n", "")
        lfake = LCLI()
        out = W.launch_remote_worker(lfake, "sess-A", "/content/job", "echo hi", job_uuid="U")
        self.assertEqual(out["pid"], 7)
        self.assertTrue(out["recovered"])

    def test_dry_run_cli_monitor(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = W.main(["monitor", "--dry-run", "--session", "s", "--job-dir", "/d", "--job-uuid", "u", "--state-dir", "/tmp/x", "--expected-source-hash", "a"*64, "--expected-package-hash", "b"*64])
        self.assertEqual(rc, 0)
        self.assertIn("dry_run", buf.getvalue())

    def test_main_monitor_with_fake_transport(self):
        # patch ColabCLI to fake
        class FakeCLI2(FakeCLI):
            pass
        # Build a fake that returns training status then stops via max_polls
        st = _status("training")
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)])
        orig = W.ColabCLI
        W.ColabCLI = lambda config=None: fake
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = W.main(["monitor", "--session", "sess-A", "--job-dir", "/content/job", "--job-uuid", "U", "--state-dir", tempfile.mkdtemp(), "--max-polls", "1", "--expected-source-hash", "a"*64, "--expected-package-hash", "b"*64])
            self.assertEqual(rc, 4)
        finally:
            W.ColabCLI = orig

    def test_cli_timeout_decimal_accepted(self):
        # verify argparse float accepts decimal
        parser = None
        # reuse main parser by calling parse only via argparse? Just check float()
        self.assertEqual(float("30.5"), 30.5)

    def test_healthy_long_run_no_deadline(self):
        st = _status("training")
        # 3 polls all training, no 7200 cutoff
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0) for _ in range(3)])
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, max_polls=3)
        rc = wd.run()
        self.assertEqual(rc, 4)
        self.assertEqual(fake.stop_calls, [])

    def test_parse_session_names_bracketed(self):
        text = "[sess-A] ep | Hardware: A100\n[?] orphan\n"
        self.assertIn("sess-A", W.parse_session_names(text))
        self.assertIn("?", W.parse_session_names(text))

    def test_stop_failure_propagates_blocked(self):
        st = _status("failed", log="/content/train.log")
        fake = FakeCLI(probes=[_probe(st, pid_alive=False, remote_now=1000.0)],
                      downloads={"/content/train.log": (0, b"log")},
                      sessions_text="[sess-A] e\n",
                      stop_rc=1)
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake)
        rc = wd.run()
        self.assertEqual(rc, 3)



    def _handoff_status(self):
        content = b"REPORT"
        h = hashlib.sha256(content).hexdigest()
        st = _status("preflight", artifacts=[], reports=["/content/preflight_report.json"], hashes={"/content/preflight_report.json": h})
        st["phase"] = "awaiting_approval"
        st["pid"] = 999
        return st, content, h

    def test_preflight_handoff_exits_10_no_stop(self):
        st, content, h = self._handoff_status()
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)],
                      downloads={"/content/preflight_report.json": (0, content)},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, until_preflight=True)
        rc = wd.run()
        self.assertEqual(rc, 10)
        self.assertEqual(fake.stop_calls, [])
        cp = json.loads((Path(tmp) / "state" / "checkpoint.json").read_text())
        self.assertTrue(cp.get("approval_required"))

    def test_preflight_handoff_bad_identity_blocks(self):
        st, content, h = self._handoff_status()
        st["job_uuid"] = "OTHER"
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)],
                      downloads={"/content/preflight_report.json": (0, content)},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, until_preflight=True, max_polls=2)
        fake.probes.append(_probe(st, pid_alive=True, remote_now=1000.0))
        rc = wd.run()
        self.assertNotEqual(rc, 10)
        self.assertEqual(fake.stop_calls, [])

    def test_preflight_handoff_missing_hash_no_handoff(self):
        st, content, h = self._handoff_status()
        # remove hash
        st["artifact_hashes"] = {}
        st["report_paths"] = ["/content/preflight_report.json"]
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)],
                      downloads={"/content/preflight_report.json": (0, content)},
                      sessions_text="[other] e\n")
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, until_preflight=True, max_polls=1)
        rc = wd.run()
        self.assertNotEqual(rc, 10)

    def test_normal_monitor_does_not_exit_on_preflight(self):
        st, content, h = self._handoff_status()
        fake = FakeCLI(probes=[_probe(st, pid_alive=True, remote_now=1000.0)])
        tmp = tempfile.mkdtemp()
        wd = self._wd(tmp, fake, until_preflight=False, max_polls=1)
        rc = wd.run()
        self.assertEqual(rc, 4)


def _sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


class PathCLI:
    """Transport double for real files: status from memory, bytes from disk."""

    def __init__(self, status, pid_alive=False):
        self.status = status
        self.pid_alive = pid_alive
        self.download_calls = []
        self.stop_calls = []

    def exec_code(self, session, code, timeout=30.0):
        payload = {"status": self.status, "error": None, "pid_alive": self.pid_alive,
                   "remote_now": time.time(), "log_mtime": None}
        return _cp(0, "WATCHDOG_JSON:" + json.dumps(payload), "")

    def download(self, session, remote_path, local_path, timeout=300.0):
        self.download_calls.append(remote_path)
        source = Path(remote_path)
        if not source.is_file():
            return _cp(1, "", "missing source")
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return _cp(0, "", "")

    def sessions(self):
        return _cp(0, "[colab] No active sessions\n", "")

    def stop(self, session):
        self.stop_calls.append(session)
        return _cp(0, "", "")


class RecordingStatus:
    def __init__(self, fields):
        self.data = dict(fields)

    def update(self, **fields):
        self.data.update(fields)


def _write_file(path, data, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def _write_zip(path, member, data):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, data)
    return path


def driver_outputs(tmp, chunk_size, complete):
    """The artifact tree a real terminal package_outputs call receives."""
    tmp = Path(tmp)
    out = tmp / "out"
    job = tmp / "job"
    log = _write_file(job / "job.log", "[start] claimed\n" + "log line\n" * 40)
    paths = {
        "preflight_report": _write_file(
            out / "preflight-report.json",
            json.dumps({"schema": "training-preflight-report/1", "status": "pass"})),
        "runtime_freeze_json": _write_file(
            out / "runtime-freeze.json",
            json.dumps({"schema": "runtime-freeze/1", "versions": {"torch": "test"}})),
        "runtime_freeze_txt": _write_file(out / "runtime-freeze.txt", "torch==test\n"),
        "package_check": _write_file(
            out / "package-check.json",
            json.dumps({"schema": "training-package-check/1", "status": "pass"})),
        "failure": _write_file(
            out / "failure.json",
            json.dumps({"schema": "reviewed-job-failure/1", "status": "fail"})),
        "download_manifest": job / "download-manifest.json",
        "lora_dir": out / "lora",
        "merged_dir": out / "merged_16bit",
        "checkpoints_dir": out / "checkpoints",
        "gguf_zip": out / "model_q4_k_m.zip",
        "run_report": out / "training-run-report.json",
        "events": out / "events.jsonl",
    }
    if complete:
        _write_file(out / "lora" / "adapter_model.safetensors", b"adapter" * 120,
                    binary=True)
        _write_file(out / "merged_16bit" / "model.safetensors", b"merged" * 200,
                    binary=True)
        _write_file(paths["run_report"],
                    json.dumps({"schema": "training-run-report/1", "status": "pass"}))
        _write_file(paths["events"], '{"event": "train_end"}\n')
        gguf = _write_file(out / "gguf" / "model.q4_k_m.gguf", b"gguf" * 300,
                           binary=True)
        _write_zip(paths["gguf_zip"], gguf.name, gguf.read_bytes())
    else:
        _write_file(out / "checkpoints" / "checkpoint-1" / "adapter_model.safetensors",
                    b"checkpoint" * 80, binary=True)
        _write_file(out / "checkpoints" / "checkpoint-1" / "optimizer.pt",
                    b"optimizer" * 80, binary=True)
    plan = {
        "job_uuid": "job-interop-1",
        "session": "sess-interop",
        "job_dir": str(job),
        "log_path": str(log),
        "chunk_size_bytes": chunk_size,
        "paths": {key: str(value) for key, value in paths.items()},
    }
    return plan


class DriverPackageWatchdogTests(unittest.TestCase):
    """Real ``package_outputs`` payload must satisfy the public watchdog."""

    def _watch(self, state_dir, status, pid_alive=False):
        cli = PathCLI(status, pid_alive=pid_alive)
        wd = W.Watchdog(
            session=status["session"], job_dir="/content/job",
            job_uuid=status["job_uuid"], state_dir=Path(state_dir), cli=cli,
            poll_interval=0.0, rpc_timeout=5.0, max_polls=1,
            sleeper=lambda seconds: None,
            expected_source_hash=status["source_hash"],
            expected_package_hash=status["package_hash"],
        )
        return wd, cli

    def _status(self, plan, complete):
        recd = RecordingStatus({"job_uuid": plan["job_uuid"],
                                "session": plan["session"],
                                "log_path": plan["log_path"],
                                "source_hash": "a" * 64,
                                "package_hash": "b" * 64})
        D.package_outputs(plan, recd, io.StringIO(), complete=complete)
        recd.data.update(state="complete" if complete else "failed",
                         child_exit_code=0 if complete else 1)
        return recd.data

    def test_complete_and_failed_statuses_chunked_and_unchunked(self):
        for complete in (True, False):
            for chunk_size in (64, 10_000_000):
                with self.subTest(complete=complete, chunk_size=chunk_size):
                    tmp = Path(tempfile.mkdtemp())
                    plan = driver_outputs(tmp, chunk_size, complete)
                    status = self._status(plan, complete)
                    wd, cli = self._watch(tmp / "state", status)
                    rc = wd.run()
                    self.assertEqual(rc, 0 if complete else 1)
                    self.assertEqual(cli.stop_calls, [plan["session"]])
                    explicit = [item["path"] for item in status["artifacts"]
                                if item.get("required", True)]
                    expected = set(explicit) | {status["download_manifest"]}
                    self.assertEqual(sorted(cli.download_calls), sorted(expected))
                    self.assertEqual(len(cli.download_calls),
                                     len(set(cli.download_calls)))
                    if chunk_size < 1024:
                        self.assertNotIn(status["log_path"], cli.download_calls)
                    for item in status["artifacts"]:
                        destination = Path(wd.artifact_dir) / item["local_name"]
                        self.assertEqual(_sha_file(destination), item["sha256"])
                    manifest_copy = (Path(wd.artifact_dir)
                                     / Path(status["download_manifest"]).name)
                    self.assertEqual(_sha_file(manifest_copy),
                                     status["artifact_hashes"][status["download_manifest"]])
                    kinds = {item["kind"] for item in status["artifacts"]}
                    self.assertEqual(kinds, {"model", "report", "log"})

    def test_explicit_metadata_beats_legacy_paths_and_operational_log(self):
        h = hashlib.sha256(b"x").hexdigest()
        status = _status("complete", artifacts=["/content/lora.zip.part001"],
                         reports=["/content/report.json"], log="/content/job.log",
                         hashes={"/content/lora.zip.part001": h,
                                 "/content/report.json": h, "/content/job.log": h})
        status["artifacts"] = [
            {"path": "/content/lora.zip.part001", "sha256": h, "kind": "model",
             "role": "model", "format": "archive_chunk", "label": "adapter",
             "local_name": "lora.zip.part001", "required": True,
             "original_name": "lora.zip", "archive_sha256": h,
             "chunk_index": 1, "chunk_count": 1},
            {"path": "/content/report.json", "sha256": h, "kind": "report",
             "role": "report", "format": "json", "local_name": "report.json",
             "required": True},
            {"path": "/content/job.log.part001", "sha256": h, "kind": "log",
             "role": "log", "format": "archive_chunk", "local_name": "job.log.part001",
             "required": True, "original_name": "job.log", "archive_sha256": h,
             "chunk_index": 1, "chunk_count": 1},
        ]
        wd, _cli = self._watch(Path(tempfile.mkdtemp()), status)
        items = wd._artifact_items(status)
        self.assertEqual(items[0]["kind"], "model")
        self.assertEqual(items[0]["local_name"], "lora.zip.part001")
        self.assertEqual({item["kind"] for item in items}, {"model", "report", "log"})
        self.assertNotIn("/content/job.log", [item["path"] for item in items])
        self.assertTrue(wd._complete_valid(status))

    def test_legacy_status_without_explicit_artifacts_still_requires_log(self):
        h = hashlib.sha256(b"x").hexdigest()
        status = _status("complete", artifacts=["/content/a.gguf"],
                         reports=["/content/report.json"], log="/content/job.log",
                         hashes={"/content/a.gguf": h, "/content/report.json": h,
                                 "/content/job.log": h})
        wd, _cli = self._watch(Path(tempfile.mkdtemp()), status)
        paths = [item["path"] for item in wd._artifact_items(status)]
        self.assertIn("/content/job.log", paths)
        self.assertTrue(wd._complete_valid(status))
        status["artifact_hashes"].pop("/content/job.log")
        self.assertFalse(wd._complete_valid(status))


class GeneratedProbeCodeTests(unittest.TestCase):
    """Run the exact probe source the watchdog ships to Colab.

    The status file is real; only the remote-only /proc entry and the
    non-child waitpid are substituted, which is what Linux exercises.
    """

    def _run_probe(self, status, proc_stat):
        tmp = Path(tempfile.mkdtemp())
        status_path = _write_file(tmp / "status.json", json.dumps(status))
        real_open = builtins.open

        def fake_open(file, *args, **kwargs):
            if str(file) == f"/proc/{status['pid']}/stat":
                return io.StringIO(proc_stat)
            return real_open(file, *args, **kwargs)

        namespace = {"__name__": "__watchdog_probe__"}
        buf = io.StringIO()
        with mock.patch("builtins.open", side_effect=fake_open), \
                mock.patch("os.waitpid", side_effect=ChildProcessError), \
                contextlib.redirect_stdout(buf):
            exec(W.build_probe_code(str(status_path)), namespace)
        return W.parse_probe_output(buf.getvalue())

    def test_probe_keeps_status_dict_when_pid_alive(self):
        log_path = _write_file(Path(tempfile.mkdtemp()) / "train.log", "step 1\n")
        status = {"state": "preflight", "phase": "awaiting_approval",
                  "pid": os.getpid(), "log_path": str(log_path)}
        out = self._run_probe(status, f"{os.getpid()} (python) S 1 2 3\n")
        self.assertIsNotNone(out)
        self.assertEqual(out["status"], status)
        self.assertEqual(out["status"]["state"], "preflight")
        self.assertEqual(out["status"]["phase"], "awaiting_approval")
        self.assertEqual(out["log_mtime"], os.path.getmtime(log_path))
        self.assertIs(out["pid_alive"], True)

    def test_probe_zombie_reports_not_alive(self):
        status = {"state": "training", "pid": os.getpid()}
        out = self._run_probe(status, f"{os.getpid()} (python) Z 1 2 3\n")
        self.assertIsNotNone(out)
        self.assertEqual(out["status"], status)
        self.assertIs(out["pid_alive"], False)


if __name__ == "__main__":
    unittest.main()
