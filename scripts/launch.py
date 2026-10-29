#!/usr/bin/env python3
"""Cross-platform application launcher and warmup orchestrator for ask-this-book (NekoHon).

Handles runtime preparation, Ollama environment optimization, port hygiene,
background server initialization, and readiness blocking.

Usage:
    python scripts/launch.py
    python scripts/launch.py --open
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from preflight import wait_for_warmup
from server import HOST, PORT, ollama_up

# Recommended Ollama environment variables for instant inference (measured 2026-10-18):
# OLLAMA_NUM_PARALLEL=1 keeps 100% GPU with 2.2 GB VRAM (vs 2.7 GB at 4) and 38.4ms TTFT (vs 44.7ms).
# OLLAMA_FLASH_ATTENTION=1 cuts median TTFT from 72.7ms to 33.4ms and total time 1338.5ms to 224.3ms.
RECOMMENDED_ENV = {
    "OLLAMA_KEEP_ALIVE": "10m",
    "OLLAMA_MAX_LOADED_MODELS": "4",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_FLASH_ATTENTION": "1",
}


def apply_recommended_env():
    """Ensure Ollama environment settings are applied to the process and children."""
    for key, val in RECOMMENDED_ENV.items():
        if key not in os.environ:
            os.environ[key] = val


def ensure_ollama_running(timeout=10.0):
    """Verify Ollama is reachable on localhost:11434; attempt start if down."""
    if ollama_up():
        return True

    print("[launcher] Ollama service is not responding. Attempting to start...")
    started = False

    # Check Windows local app data install
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    win_ollama = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
    if os.path.isfile(win_ollama):
        try:
            subprocess.Popen([win_ollama, "app"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started = True
        except Exception:
            pass

    if not started and shutil.which("ollama"):
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started = True
        except Exception:
            pass

    if started:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            if ollama_up():
                print("[launcher] Ollama service connected successfully.")
                return True

    print("[launcher] Warning: Ollama service could not be automatically started.")
    return False


def get_process_cmdline(pid):
    """Retrieve command line for a given process ID."""
    if sys.platform == "win32":
        if shutil.which("wmic"):
            try:
                res = subprocess.run(
                    ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                    if len(lines) > 1 and lines[0].lower() == "commandline":
                        return lines[1]
            except Exception:
                pass
        try:
            ps_cmd = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return ""
    else:
        try:
            res = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        try:
            proc_file = Path(f"/proc/{pid}/cmdline")
            if proc_file.is_file():
                return proc_file.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        return ""


def is_server_process(cmdline):
    """Check if command line is a Python process running server.py."""
    if not cmdline:
        return False
    cmd_lower = cmdline.lower()
    return "python" in cmd_lower and "server.py" in cmd_lower


def find_listening_pids(port):
    """Find unique PIDs listening on the specified port."""
    pids = set()
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(
                "netstat -ano -p tcp",
                shell=True,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for line in output.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == "TCP":
                    local_addr = parts[1]
                    state = parts[3].upper() if len(parts) >= 5 else ""
                    if local_addr.endswith(f":{port}") and state == "LISTENING":
                        pid_str = parts[-1]
                        if pid_str.isdigit() and int(pid_str) > 0 and int(pid_str) != os.getpid():
                            pids.add(int(pid_str))
        except Exception:
            pass
    else:
        if shutil.which("lsof"):
            try:
                res = subprocess.run(
                    ["lsof", "-ti", f"tcp:{port}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        line = line.strip()
                        if line.isdigit() and int(line) > 0 and int(line) != os.getpid():
                            pids.add(int(line))
            except Exception:
                pass
        if not pids and shutil.which("fuser"):
            try:
                res = subprocess.run(
                    ["fuser", f"{port}/tcp"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    for token in res.stdout.split():
                        if token.isdigit() and int(token) > 0 and int(token) != os.getpid():
                            pids.add(int(token))
            except Exception:
                pass
    return sorted(pids)


def clear_port_8000(port=None, dry_run=False):
    """Ensure no stale process is listening on server port.

    Only kills a process if it is a python process whose command line includes server.py.
    Otherwise prints a clear error message naming the PID and exits non-zero.
    """
    if port is None:
        port = int(os.environ.get("PORT", PORT))
    else:
        port = int(port)

    pids = find_listening_pids(port)
    if not pids:
        return

    for pid in pids:
        cmdline = get_process_cmdline(pid)
        if not is_server_process(cmdline):
            desc = cmdline if cmdline else "unknown command line"
            print(
                f"[launcher] Error: Port {port} is occupied by process PID {pid} ({desc}). "
                f"Refusing to kill non-server.py process.",
                file=sys.stderr,
            )
            sys.exit(1)

        if dry_run:
            print(f"[launcher] [dry-run] Found stale server.py process on port {port} (PID {pid}): {cmdline}")
        else:
            print(f"[launcher] Terminating stale server.py process on port {port} (PID {pid})...")
            if sys.platform == "win32":
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            else:
                try:
                    os.kill(pid, 9)
                except Exception:
                    subprocess.run(["kill", "-9", str(pid)], capture_output=True)


clear_port = clear_port_8000


def main():
    parser = argparse.ArgumentParser(description="ask-this-book (NekoHon) App Launcher")
    parser.add_argument("--open", action="store_true", help="Open default browser once server is ready")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", PORT)), help=f"Server port (default: {PORT} or $PORT)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report actions without launching server or killing processes")
    args = parser.parse_args()

    port = args.port
    apply_recommended_env()

    print("=" * 76)
    print(" ask-this-book | Launching Engine with Resident Warmup")
    print("=" * 76)

    # 1. Ensure Ollama is up
    if not args.dry_run:
        ensure_ollama_running()
    else:
        print(f"[launcher] [dry-run] Ollama status: {'running' if ollama_up() else 'down'}")

    # 2. Port hygiene
    clear_port_8000(port=port, dry_run=args.dry_run)
    if args.dry_run:
        print(f"[launcher] [dry-run] Port {port} hygiene check completed successfully.")
        return 0

    # 3. Start server.py in background
    runs_dir = REPO_ROOT / "artifacts" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    out_file = runs_dir / "stage1-server.out"
    err_file = runs_dir / "stage1-server.err"

    print(f"[launcher] Starting server on http://{HOST}:{port}...")
    server_cmd = [sys.executable, "server.py", "--port", str(port)]
    server_env = os.environ.copy()
    server_env["PORT"] = str(port)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    with open(out_file, "a", encoding="utf-8") as out, open(err_file, "a", encoding="utf-8") as err:
        subprocess.Popen(
            server_cmd,
            cwd=str(REPO_ROOT),
            stdout=out,
            stderr=err,
            env=server_env,
            creationflags=flags,
        )

    # 4. Block readiness until warmup completes
    print("[launcher] Waiting for startup warm-up (in-process caches + model residency)...")
    ok, warm = wait_for_warmup(server_url=f"http://{HOST}:{port}/health", timeout=60.0)

    if ok:
        ans_m = warm.get("answer_model", "unknown")
        emb_m = warm.get("embed_model", "unknown")
        dur = warm.get("duration_s", 0)
        print(f"[launcher] Ready to serve! Warmup completed in {dur}s.")
        print(f"           - Answer Model : {ans_m} (Resident in memory)")
        print(f"           - Embedder     : {emb_m} (Resident in memory)")
        print(f"           - URL          : http://{HOST}:{port}/")
        print("=" * 76)
        if args.open:
            webbrowser.open(f"http://{HOST}:{port}/")
        return 0
    else:
        err = warm.get("error", "unknown error")
        print(f"[launcher] Error: Engine warmup failed: {err}")
        print("=" * 76)
        return 1


if __name__ == "__main__":
    sys.exit(main())
