#!/usr/bin/env python3
"""Deterministic local watchdog for a Colab training job."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

TERMINAL_STATES = {"complete", "failed"}
KNOWN_STATES = {"setup", "preflight", "training", "export", "complete", "failed", "unknown"}
DEFAULT_STALE_HEARTBEAT = 300.0
DEFAULT_RPC_TIMEOUT = 30.0


class CheckpointBindingError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_event(path: Path, event: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


class ColabCLI:
    def __init__(self, binary: str = "colab", config: Optional[str] = None, timeout: float = 120.0):
        self.binary = binary
        self.config = config
        self.timeout = timeout

    def _base(self) -> List[str]:
        cmd = [self.binary]
        if self.config:
            cmd = [self.binary, "--config", self.config]
        return cmd

    def _run(self, args: List[str], input_text: Optional[str] = None, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
        cmd = self._base() + list(args)
        to = self.timeout if timeout is None else timeout
        try:
            return subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=to)
        except subprocess.TimeoutExpired as e:
            def _text(value):
                if isinstance(value, bytes):
                    return value.decode("utf-8", "replace")
                return value or ""
            return subprocess.CompletedProcess(cmd, 124, stdout=_text(e.stdout),
                                               stderr=_text(e.stderr) + "\nTIMEOUT")

    def sessions(self) -> subprocess.CompletedProcess:
        return self._run(["sessions"], timeout=30.0)

    def status(self, session: str) -> subprocess.CompletedProcess:
        return self._run(["status", "-s", session], timeout=30.0)

    def exec_code(self, session: str, code: str, timeout: float = DEFAULT_RPC_TIMEOUT) -> subprocess.CompletedProcess:
        return self._run(["exec", "-s", session, "--timeout", str(timeout)], input_text=code, timeout=timeout + 10.0)

    def download(self, session: str, remote_path: str, local_path: str, timeout: float = 300.0) -> subprocess.CompletedProcess:
        return self._run(["download", "-s", session, remote_path, local_path], timeout=timeout)

    def stop(self, session: str) -> subprocess.CompletedProcess:
        return self._run(["stop", "-s", session], timeout=60.0)


def parse_session_names(text: str) -> List[str]:
    import re
    names: List[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("[colab]"):
            continue
        for m in re.finditer(r"\[([^\]]+)\]", line):
            names.append(m.group(1))
    return names


def build_probe_code(status_path: str) -> str:
    return (
        "import json, os, time\n"
        f"STATUS = {status_path!r}\n"
        "out = {'status': None, 'error': None, 'pid_alive': None, 'remote_now': time.time(), 'log_mtime': None}\n"
        "try:\n"
        "    with open(STATUS) as f:\n"
        "        out['status'] = json.load(f)\n"
        "except FileNotFoundError:\n"
        "    out['error'] = 'missing_status'\n"
        "except Exception as e:\n"
        "    out['error'] = repr(e)\n"
        "st = out['status']\n"
        "if isinstance(st, dict):\n"
        "    pid = st.get('pid')\n"
        "    if isinstance(pid, int):\n"
        "        alive = True\n"
        "        try:\n"
        "            rpid, _ = os.waitpid(pid, os.WNOHANG)\n"
        "            if rpid == pid:\n"
        "                alive = False\n"
        "        except ChildProcessError:\n"
        "            pass\n"
        "        except Exception:\n"
        "            pass\n"
        "        try:\n"
        "            proc_stat = open('/proc/%d/stat' % pid).read().split()\n"
        "            if len(proc_stat) > 2 and proc_stat[2] == 'Z':\n"
        "                alive = False\n"
        "        except FileNotFoundError:\n"
        "            alive = False\n"
        "        except Exception:\n"
        "            pass\n"
        "        if alive:\n"
        "            try:\n"
        "                os.kill(pid, 0)\n"
        "            except OSError:\n"
        "                alive = False\n"
        "        out['pid_alive'] = alive\n"
        "    lp = st.get('log_path')\n"
        "    if isinstance(lp, str):\n"
        "        try:\n"
        "            out['log_mtime'] = os.path.getmtime(lp)\n"
        "        except OSError:\n"
        "            out['log_mtime'] = None\n"
        "print('WATCHDOG_JSON:' + json.dumps(out))\n"
    )


def parse_probe_output(stdout: str) -> Optional[Dict[str, Any]]:
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("WATCHDOG_JSON:"):
            try:
                return json.loads(line[len("WATCHDOG_JSON:"):])
            except json.JSONDecodeError:
                return None
    return None


class Watchdog:
    def __init__(
        self,
        session: str,
        job_dir: str,
        job_uuid: str,
        state_dir: Path,
        cli: ColabCLI,
        poll_interval: float = 30.0,
        rpc_timeout: float = DEFAULT_RPC_TIMEOUT,
        stale_heartbeat: float = DEFAULT_STALE_HEARTBEAT,
        expected_source_hash: Optional[str] = None,
        expected_package_hash: Optional[str] = None,
        artifact_dir: Optional[Path] = None,
        max_polls: Optional[int] = None,
        sleeper: Callable[[float], None] = time.sleep,
        force: bool = False,
        until_preflight: bool = False,
    ):
        self.session = session
        self.job_dir = job_dir
        self.job_uuid = job_uuid
        self.state_dir = Path(state_dir)
        self.cli = cli
        self.poll_interval = poll_interval
        self.rpc_timeout = rpc_timeout
        self.stale_heartbeat = stale_heartbeat
        if expected_source_hash is not None:
            if not (isinstance(expected_source_hash, str) and len(expected_source_hash) == 64 and all(c in "0123456789abcdef" for c in expected_source_hash)):
                raise ValueError("expected_source_hash must be 64 hex chars")
        if expected_package_hash is not None:
            if not (isinstance(expected_package_hash, str) and len(expected_package_hash) == 64 and all(c in "0123456789abcdef" for c in expected_package_hash)):
                raise ValueError("expected_package_hash must be 64 hex chars")
        if expected_source_hash is None or expected_package_hash is None:
            raise ValueError("expected source/package hashes are required")
        self.expected_source_hash = expected_source_hash
        self.expected_package_hash = expected_package_hash
        self.artifact_dir = Path(artifact_dir) if artifact_dir else (self.state_dir / "artifacts")
        self.max_polls = max_polls
        self.sleeper = sleeper
        self.force = force
        self.until_preflight = until_preflight

        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.marker_path = self.state_dir / "watchdog.lock"
        self.checkpoint_path = self.state_dir / "checkpoint.json"
        self.events_path = self.state_dir / "events.jsonl"

        self.remote_status_path = f"{job_dir.rstrip('/')}/status.json"
        self._polls = 0
        self._terminal = False
        self._blocked = False
        self._handoff_ready = False
        self._last_state = "unknown"

    def acquire_marker(self) -> bool:
        lock_path = self.marker_path.with_suffix(self.marker_path.suffix + ".lock")
        try:
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError):
            os.close(fd)
            return False
        self._lock_fd = fd
        # write complete marker atomically
        data = {"pid": os.getpid(), "started_at": time.time()}
        tmp = self.marker_path.with_suffix(self.marker_path.suffix + ".tmp." + str(os.getpid()))
        atomic_write_json(tmp, data)
        try:
            os.link(tmp, self.marker_path)
        except FileExistsError:
            # stale: if pid dead, replace
            try:
                existing = json.loads(self.marker_path.read_text())
                pid = int(existing.get("pid", -1))
                if pid > 0 and self._pid_alive(pid) and not self.force:
                    tmp.unlink(missing_ok=True)
                    return False
            except Exception:
                pass
            try:
                self.marker_path.unlink()
            except FileNotFoundError:
                pass
            os.link(tmp, self.marker_path)
        tmp.unlink(missing_ok=True)
        return True

    def release_marker(self) -> None:
        try:
            data = json.loads(self.marker_path.read_text())
            if int(data.get("pid", -1)) == os.getpid():
                self.marker_path.unlink()
        except Exception:
            pass
        fd = getattr(self, "_lock_fd", None)
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(fd)
            except Exception:
                pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def log_event(self, kind: str, payload: Dict[str, Any]) -> None:
        append_event(self.events_path, {"ts": time.time(), "kind": kind, **payload})

    def _binding(self) -> Dict[str, Any]:
        return {"session": self.session, "job_dir": self.job_dir, "job_uuid": self.job_uuid}

    def save_checkpoint(self, data: Dict[str, Any]) -> None:
        existing = {}
        if self.checkpoint_path.exists():
            try:
                existing = json.loads(self.checkpoint_path.read_text())
            except Exception:
                existing = {}
        if existing:
            for k in ("session", "job_dir", "job_uuid"):
                if k in existing and existing.get(k) != self._binding().get(k):
                    raise CheckpointBindingError(f"checkpoint bound to different {k}")
        merged = dict(data)
        merged.update(self._binding())
        atomic_write_json(self.checkpoint_path, merged)

    def load_checkpoint(self) -> Dict[str, Any]:
        if self.checkpoint_path.exists():
            try:
                cp = json.loads(self.checkpoint_path.read_text())
            except Exception:
                return {}
            for k in ("session", "job_dir", "job_uuid"):
                if k in cp and cp.get(k) != self._binding().get(k):
                    self.log_event("checkpoint_binding_mismatch", {"key": k})
                    return {}
            return cp
        return {}

    def validate_identity(self, status: Dict[str, Any]) -> Optional[str]:
        if status.get("job_uuid") != self.job_uuid:
            return "job_uuid_mismatch"
        if status.get("session") != self.session:
            return "session_mismatch"
        if self.expected_source_hash is not None and status.get("source_hash") != self.expected_source_hash:
            return "source_hash_mismatch"
        if self.expected_package_hash is not None and status.get("package_hash") != self.expected_package_hash:
            return "package_hash_mismatch"
        return None

    def _is_stale(self, remote: Dict[str, Any], status: Dict[str, Any]) -> bool:
        rn = remote.get("remote_now")
        hb = status.get("heartbeat_at", status.get("updated_at"))
        if not isinstance(rn, (int, float)) or not isinstance(hb, (int, float)):
            return False
        return (rn - hb) > self.stale_heartbeat

    def _has_exit_proof(self, status: Dict[str, Any]) -> bool:
        return status.get("child_exit_code") is not None

    def _is_model_artifact(self, it: Dict[str, Any], status: Dict[str, Any]) -> bool:
        if it.get("kind") == "model":
            return True
        if it.get("role") == "model":
            return True
        if it.get("model_format") in ("gguf", "safetensors"):
            return True
        path = str(it.get("path", ""))
        low = path.lower()
        if low.endswith(".gguf") or low.endswith(".safetensors"):
            return True
        manifest = status.get("model_manifest") or status.get("model_chunks")
        if isinstance(manifest, list) and path in manifest:
            return True
        return False

    def _complete_valid(self, status: Dict[str, Any]) -> bool:
        if status.get("child_exit_code") != 0:
            return False
        if not status.get("source_hash") or not status.get("package_hash"):
            return False
        if status.get("source_hash") != self.expected_source_hash:
            return False
        if status.get("package_hash") != self.expected_package_hash:
            return False
        if status.get("session") != self.session:
            return False
        items = self._artifact_items(status)
        models = [it for it in items if it.get("required") and self._is_model_artifact(it, status)]
        reports = [it for it in items if it.get("required") and it.get("kind") == "report"]
        logs = [it for it in items if it.get("required") and it.get("kind") == "log"]
        if not models:
            return False
        if not reports:
            return False
        if not logs:
            return False
        for it in items:
            if it.get("required") and not it.get("sha256"):
                return False
        return True

    def _preflight_valid(self, status: Dict[str, Any]) -> bool:
        if status.get("source_hash") != self.expected_source_hash:
            return False
        if status.get("package_hash") != self.expected_package_hash:
            return False
        if status.get("session") != self.session:
            return False
        if not status.get("source_hash") or not status.get("package_hash"):
            return False
        items = self._artifact_items(status)
        reports = [it for it in items if it.get("required") and it.get("kind") in ("report", "log")]
        if not reports:
            return False
        for it in reports:
            if not it.get("sha256"):
                return False
        return True

    def poll_once(self) -> Dict[str, Any]:
        self._polls += 1
        cp = self.load_checkpoint()
        remote = None
        transport_error = None
        proc = self.cli.exec_code(self.session, build_probe_code(self.remote_status_path), timeout=self.rpc_timeout)
        if proc.returncode != 0:
            transport_error = (proc.stderr or proc.stdout or "").strip()[:500]
        else:
            remote = parse_probe_output(proc.stdout)
            if remote is None:
                transport_error = "unparseable_probe_output"

        result: Dict[str, Any] = {
            "poll": self._polls,
            "ts": time.time(),
            "transport_error": transport_error,
            "remote": remote,
        }

        if transport_error is not None:
            self.log_event("transport_error", {"error": transport_error})
            try:
                self.save_checkpoint({**cp, "last_poll": result["ts"], "transport_error": transport_error, "state": self._last_state})
            except Exception as e:
                self.log_event("checkpoint_error", {"error": repr(e)})
            return result

        assert remote is not None
        status = remote.get("status")
        pid_alive = remote.get("pid_alive")
        stale = self._is_stale(remote, status) if isinstance(status, dict) else False
        identity_error = None
        state = "unknown"
        terminal = False
        if isinstance(status, dict):
            state = str(status.get("state", "unknown"))
            if state not in KNOWN_STATES:
                state = "unknown"
            identity_error = self.validate_identity(status)
            if identity_error:
                self.log_event("identity_mismatch", {"error": identity_error, "remote_state": state})
            # terminal acceptance: dead pid + exit proof; stale heartbeat alone not enough
            if state in TERMINAL_STATES and identity_error is None and pid_alive is False:
                if state == "complete":
                    if self._complete_valid(status):
                        terminal = True
                else:
                    # failed: require exit proof
                    if self._has_exit_proof(status):
                        terminal = True
            # also accept stale old terminal if exit proof present (already covered by pid dead)
        else:
            state = "unknown"
            self.log_event("missing_status", {"remote_error": remote.get("error")})

        result.update({
            "state": state,
            "pid_alive": pid_alive,
            "stale_heartbeat": stale,
            "identity_error": identity_error,
            "terminal": terminal,
            "remote_error": remote.get("error"),
        })

        self._last_state = state if identity_error is None else "unknown"
        try:
            self.save_checkpoint({
                "last_poll": result["ts"],
                "polls": self._polls,
                "state": self._last_state,
                "remote_state": state,
                "pid_alive": pid_alive,
                "stale_heartbeat": stale,
                "identity_error": identity_error,
                "terminal": terminal,
                "transport_error": None,
            })
        except Exception as e:
            self.log_event("checkpoint_error", {"error": repr(e)})
        self.log_event("poll", {"state": state, "terminal": terminal, "pid_alive": pid_alive, "stale": stale})

        # handoff: preflight awaiting approval (only in until_preflight mode)
        handoff = False
        if self.until_preflight and isinstance(status, dict) and state == "preflight" and status.get("phase") == "awaiting_approval" and identity_error is None:
            if self._preflight_valid(status):
                handoff = True
            else:
                self.log_event("preflight_invalid", {"state": state})

        if handoff:
            ok = self.download_artifacts(status, require_hash=True)
            if not ok:
                self._blocked = True
                self.log_event("blocked", {"reason": "preflight_download_failed"})
            else:
                self.save_checkpoint({
                    "last_poll": result["ts"],
                    "polls": self._polls,
                    "state": "preflight",
                    "remote_state": state,
                    "approval_required": True,
                    "job_uuid": self.job_uuid,
                    "session": self.session,
                    "job_dir": self.job_dir,
                })
                self.log_event("preflight_handoff", {"job_uuid": self.job_uuid})
                self._handoff_ready = True

        if terminal and not handoff:
            self._terminal = True
            if state == "complete":
                ok = self.handle_complete(status)
                if not ok:
                    self._blocked = True
                    self._terminal = False
                    self.log_event("blocked", {"reason": "artifact_download_or_verify_failed"})
            else:
                ok = self.handle_failed(status)
                if not ok:
                    self._blocked = True
                    self._terminal = False
                    self.log_event("blocked", {"reason": "evidence_download_or_stop_failed"})
        return result

    def handle_complete(self, status: Dict[str, Any]) -> bool:
        if not self._complete_valid(status):
            self.log_event("invalid_complete", {})
            return False
        ok = self.download_artifacts(status, require_hash=True)
        if not ok:
            return False
        if not self.stop_owned_session():
            self.log_event("stop_not_confirmed", {})
            return False
        self.log_event("complete", {"job_uuid": self.job_uuid})
        return True

    def handle_failed(self, status: Dict[str, Any]) -> bool:
        ok = self.download_artifacts(status, require_hash=False)
        if not ok:
            self.log_event("evidence_download_failed", {})
            return False
        if not self.stop_owned_session():
            self.log_event("stop_not_confirmed", {})
            return False
        self.log_event("failed", {"job_uuid": self.job_uuid, "child_exit_code": status.get("child_exit_code")})
        return True

    def _artifact_items(self, status: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        seen = set()
        hashes = status.get("artifact_hashes") or {}

        def add(path: str, sha256: Optional[str], required: Any, kind: str,
                local_name: Optional[str] = None) -> None:
            if not path or path in seen:
                return
            seen.add(path)
            item = {"path": path, "sha256": sha256, "required": required,
                    "kind": kind}
            if local_name:
                item["local_name"] = local_name
            items.append(item)

        # Explicit per-path metadata wins: the driver describes kind, role,
        # format and destination for every chunk it publishes. Legacy path
        # lists only fill in paths the explicit list does not already cover.
        for a in status.get("artifacts", []) or []:
            if isinstance(a, dict) and a.get("path"):
                add(a["path"], a.get("sha256", hashes.get(a["path"])),
                    a.get("required", True), a.get("kind", "artifact"),
                    a.get("local_name"))
        explicit_log = any(it["kind"] == "log" and it.get("sha256") for it in items)
        for p in status.get("artifact_paths", []) or []:
            add(p, hashes.get(p), True, "artifact")
        for p in status.get("report_paths", []) or []:
            add(p, hashes.get(p), True, "report")
        log_path = status.get("log_path")
        # The operational log_path stays an item only when no explicit hashed
        # log chunk covers it; otherwise it would demand an unhashed re-download.
        if log_path and not explicit_log:
            add(log_path, hashes.get(log_path), True, "log")
        return items

    def download_artifacts(self, status: Dict[str, Any], require_hash: bool) -> bool:
        child_exit = status.get("child_exit_code")
        if status.get("state") == "complete":
            if child_exit != 0:
                self.log_event("bad_exit_code", {"child_exit_code": child_exit})
                return False
        items = self._artifact_items(status)
        planned = []
        seen_dest = set()
        for it in items:
            if not it.get("required"):
                continue
            remote_path = it["path"]
            local_name = it.get("local_name") or os.path.basename(remote_path)
            if (not local_name) or local_name in (".", "/") or local_name.startswith("/") or "\\" in local_name:
                self.log_event("bad_artifact_name", {"path": remote_path, "name": local_name})
                return False
            if ".." in Path(local_name).parts:
                self.log_event("bad_artifact_name", {"path": remote_path, "name": local_name})
                return False
            if "/" in local_name or "\\" in local_name:
                self.log_event("bad_artifact_name", {"path": remote_path, "name": local_name})
                return False
            dest = (self.artifact_dir / local_name).resolve()
            try:
                dest.relative_to(self.artifact_dir.resolve())
            except ValueError:
                self.log_event("artifact_escape", {"path": remote_path, "dest": str(dest)})
                return False
            if str(dest) in seen_dest:
                self.log_event("duplicate_destination", {"path": remote_path, "dest": str(dest)})
                return False
            seen_dest.add(str(dest))
            planned.append((it, dest))
        for it, dest in planned:
            remote_path = it["path"]
            res = self.cli.download(self.session, remote_path, str(dest), timeout=300.0)
            if res.returncode != 0:
                self.log_event("download_failed", {"path": remote_path, "stderr": (res.stderr or "")[:300]})
                return False
            if not dest.exists():
                self.log_event("download_missing", {"path": remote_path})
                return False
            expected = it.get("sha256")
            if expected:
                actual = sha256_file(dest)
                if actual != expected:
                    self.log_event("hash_mismatch", {"path": remote_path, "expected": expected, "actual": actual})
                    return False
            elif require_hash:
                self.log_event("missing_hash", {"path": remote_path})
                return False
        return True

    def stop_owned_session(self) -> bool:
        res = self.cli.stop(self.session)
        if res.returncode != 0:
            self.log_event("stop_failed", {"stderr": (res.stderr or "")[:300]})
            return False
        for _ in range(3):
            try:
                out = self.cli.sessions()
            except Exception as e:
                self.log_event("session_verify_error", {"error": repr(e)})
                return False
            if out.returncode != 0:
                self.log_event("session_verify_transport", {"stderr": (out.stderr or "")[:300]})
                return False
            text = out.stdout or ""
            if "[colab] No active sessions" in text or "No active sessions found" in text:
                self.log_event("stopped_verified", {"session": self.session})
                return True
            names = parse_session_names(text)
            if not names:
                self.log_event("session_verify_unparseable", {"text": text[:200]})
                return False
            if self.session not in names:
                self.log_event("stopped_verified", {"session": self.session})
                return True
            time.sleep(1.0)
        self.log_event("session_still_present", {"session": self.session})
        return False

    def run(self) -> int:
        if not self.acquire_marker():
            self.log_event("double_launch_blocked", {"marker": str(self.marker_path)})
            print(f"[watchdog] another instance is running (marker {self.marker_path})", file=sys.stderr)
            return 2
        caffeinate_proc = None
        try:
            if getattr(self, "_caffeinate", False):
                try:
                    caffeinate_proc = subprocess.Popen(["caffeinate", "-i"])
                except FileNotFoundError:
                    pass
            self.log_event("start", {"session": self.session, "job_uuid": self.job_uuid})
            while True:
                if self.max_polls is not None and self._polls >= self.max_polls:
                    break
                res = self.poll_once()
                if self._handoff_ready:
                    print("[watchdog] PREFLIGHT HANDOFF: approval required; VM left running", file=sys.stderr)
                    return 10
                if self._blocked:
                    print("[watchdog] BLOCKED: cleanup not confirmed; VM left running for human decision", file=sys.stderr)
                    return 3
                if self._terminal:
                    st = self._last_state
                    return 0 if st == "complete" else 1
                err = res.get("transport_error")
                wait = self.poll_interval
                if err is not None:
                    wait = min(self.poll_interval * (2 ** min(self._polls, 6)), 300.0)
                self.sleeper(wait)
            self.log_event("max_polls_reached", {"polls": self._polls})
            print("[watchdog] max polls reached without terminal state", file=sys.stderr)
            return 4
        finally:
            if caffeinate_proc is not None:
                try:
                    caffeinate_proc.terminate()
                except Exception:
                    pass
            self.release_marker()


def recover_remote_worker(cli: ColabCLI, session: str, job_dir: str, timeout: float = DEFAULT_RPC_TIMEOUT) -> Dict[str, Any]:
    code = (
        "import json, os\n"
        f"JOB_DIR = {job_dir!r}\n"
        "pid = None\n"
        "try:\n"
        "    pid = int(open(os.path.join(JOB_DIR, 'worker.pid')).read().strip())\n"
        "except Exception:\n"
        "    pid = None\n"
        "status = None\n"
        "try:\n"
        "    status = json.load(open(os.path.join(JOB_DIR, 'status.json')))\n"
        "except Exception:\n"
        "    status = None\n"
        "alive = None\n"
        "if isinstance(pid, int):\n"
        "    try:\n"
        "        os.kill(pid, 0); alive = True\n"
        "    except OSError:\n"
        "        alive = False\n"
        "print('RECOVERED:' + json.dumps({'pid': pid, 'alive': alive, 'status': status}))\n"
    )
    proc = cli.exec_code(session, code, timeout=timeout)
    info = None
    for line in (proc.stdout or "").splitlines():
        if line.strip().startswith("RECOVERED:"):
            try:
                info = json.loads(line.strip()[len("RECOVERED:"):])
            except json.JSONDecodeError:
                info = None
    return {"returncode": proc.returncode, "info": info, "stdout": proc.stdout, "stderr": proc.stderr}


def launch_remote_worker(cli: ColabCLI, session: str, job_dir: str, remote_command: str, job_uuid: Optional[str] = None, timeout: float = DEFAULT_RPC_TIMEOUT) -> Dict[str, Any]:
    identity = sha256_text(f"{job_uuid or ''}:{remote_command}")
    marker_name = "job.launch.marker"
    code = (
        "import subprocess, os, json, fcntl\n"
        f"JOB_DIR = {job_dir!r}\n"
        f"CMD = {remote_command!r}\n"
        f"IDENTITY = {identity!r}\n"
        "os.makedirs(JOB_DIR, exist_ok=True)\n"
        "marker = os.path.join(JOB_DIR, 'job.launch.marker')\n"
        "fd = None\n"
        "try:\n"
        "    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)\n"
        "except FileExistsError:\n"
        "    fd = None\n"
        "if fd is None:\n"
        "    # recover existing\n"
        "    try:\n"
        "        info = json.load(open(marker))\n"
        "    except Exception:\n"
        "        info = {}\n"
        "    pid = info.get('pid')\n"
        "    alive = None\n"
        "    if isinstance(pid, int):\n"
        "        try:\n"
        "            os.kill(pid, 0); alive = True\n"
        "        except OSError:\n"
        "            alive = False\n"
        "    print('RECOVERED_PID:' + json.dumps({'pid': pid, 'alive': alive, 'identity': info.get('identity')}))\n"
        "else:\n"
        "    with os.fdopen(fd, 'w') as f:\n"
        "        json.dump({'identity': IDENTITY, 'started_at': __import__('time').time()}, f)\n"
        "        f.flush(); os.fsync(f.fileno())\n"
        "    log = os.path.join(JOB_DIR, 'worker.log')\n"
        "    with open(log, 'a') as lf:\n"
        "        p = subprocess.Popen(['bash','-c', CMD], start_new_session=True, stdout=lf, stderr=subprocess.STDOUT)\n"
        "        # record pid in marker\n"
        "        data = json.load(open(marker))\n"
        "        data['pid'] = p.pid\n"
        "        json.dump(data, open(marker, 'w'))\n"
        "        with open(os.path.join(JOB_DIR, 'worker.pid'), 'w') as pf:\n"
        "            pf.write(str(p.pid))\n"
        "        print('LAUNCHED_PID:' + str(p.pid))\n"
    )
    proc = cli.exec_code(session, code, timeout=timeout)
    pid = None
    recovered = False
    for line in (proc.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("LAUNCHED_PID:"):
            try:
                pid = int(s.split(":", 1)[1])
            except ValueError:
                pid = None
        elif s.startswith("RECOVERED_PID:"):
            recovered = True
            try:
                info = json.loads(s[len("RECOVERED_PID:"):])
                pid = info.get("pid")
            except json.JSONDecodeError:
                pass
    if pid is None:
        # ambiguous: recover
        rec = recover_remote_worker(cli, session, job_dir, timeout=timeout)
        info = rec.get("info") or {}
        pid = info.get("pid")
        recovered = True
    return {"returncode": proc.returncode, "pid": pid, "recovered": recovered, "stdout": proc.stdout, "stderr": proc.stderr}


def add_monitor_args(p):
    p.add_argument("--session", required=True)
    p.add_argument("--job-dir", required=True)
    p.add_argument("--job-uuid", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--poll-interval", type=float, default=30.0)
    p.add_argument("--rpc-timeout", type=float, default=DEFAULT_RPC_TIMEOUT)
    p.add_argument("--stale-heartbeat", type=float, default=DEFAULT_STALE_HEARTBEAT)
    p.add_argument("--expected-source-hash", required=True)
    p.add_argument("--expected-package-hash", required=True)
    p.add_argument("--artifact-dir", default=None)
    p.add_argument("--max-polls", type=int, default=None)
    p.add_argument("--force", action="store_true")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Colab training watchdog")
    parser.add_argument("--dry-run", action="store_true", help="Inspect plan and exit without polling")
    parser.add_argument("--config", default=None, help="Colab CLI session state file (isolated)")
    parser.add_argument("--caffeinate", action="store_true", help="Prevent idle sleep on macOS")
    sub = parser.add_subparsers(dest="cmd")

    mon = sub.add_parser("monitor", help="Monitor a job until terminal/blocked")
    add_monitor_args(mon)
    mon.add_argument("--dry-run", action="store_true", help="Inspect plan and exit without polling")
    mon.add_argument("--until-preflight", action="store_true", help="Stop at preflight handoff (approval required)")

    lau = sub.add_parser("launch", help="Launch a remote OS-level background worker")
    lau.add_argument("--session", required=True)
    lau.add_argument("--job-dir", required=True)
    lau.add_argument("--remote-command", required=True)
    lau.add_argument("--job-uuid", default=None)
    lau.add_argument("--timeout", type=float, default=DEFAULT_RPC_TIMEOUT)
    lau.add_argument("--dry-run", action="store_true", help="Inspect plan and exit without polling")

    args = parser.parse_args(argv)

    if args.dry_run:
        print(json.dumps({"dry_run": True, "cmd": args.cmd, "argv": sys.argv[1:]}, indent=2))
        return 0

    cli = ColabCLI(config=args.config)

    if args.cmd == "launch":
        out = launch_remote_worker(cli, args.session, args.job_dir, args.remote_command, job_uuid=args.job_uuid, timeout=args.timeout)
        print(json.dumps(out, indent=2))
        return 0 if out["pid"] is not None else 1

    if args.cmd not in (None, "monitor"):
        parser.error(f"unknown command {args.cmd}")

    for hname in ("expected_source_hash", "expected_package_hash"):
        hv = getattr(args, hname, None)
        if not (isinstance(hv, str) and len(hv) == 64 and all(c in "0123456789abcdef" for c in hv)):
            parser.error(f"{hname} must be 64 hex chars")
    session = getattr(args, "session", None)
    job_dir = getattr(args, "job_dir", None)
    job_uuid = getattr(args, "job_uuid", None)
    state_dir = getattr(args, "state_dir", None)
    if session is None:
        parser.error("--session is required")
    if job_dir is None:
        parser.error("--job-dir is required")
    if job_uuid is None:
        parser.error("--job-uuid is required")
    if state_dir is None:
        parser.error("--state-dir is required")

    wd = Watchdog(
        session=session,
        job_dir=job_dir,
        job_uuid=job_uuid,
        state_dir=Path(state_dir),
        cli=cli,
        poll_interval=args.poll_interval,
        rpc_timeout=args.rpc_timeout,
        stale_heartbeat=args.stale_heartbeat,
        expected_source_hash=args.expected_source_hash,
        expected_package_hash=args.expected_package_hash,
        artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
        max_polls=args.max_polls,
        force=args.force,
        until_preflight=getattr(args, "until_preflight", False),
    )
    wd._caffeinate = bool(args.caffeinate)
    return wd.run()


if __name__ == "__main__":
    raise SystemExit(main())
