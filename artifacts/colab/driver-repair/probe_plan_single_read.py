#!/usr/bin/env python3
"""Probe: the driver must parse and execute the one caller-approved plan read.

A FIFO serves document A (approved) first and document B (swapped) to any
second reader. The approved SHA-256 is passed on the command line. A driver
that verifies read one and executes read two records the swapped job.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.test_run_reviewed_job import (  # noqa: E402
    DRIVER, PY, build_plan, finish, read_status, sha_bytes, sha_file,
)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="single-read-probe-"))
    try:
        plan, plan_path = build_plan(tmp, preflight_exit=1)
        approved = json.loads(Path(plan_path).read_text())
        approved["job_uuid"] = "job-approved"
        approved["session"] = "approved-session"
        approved_bytes = json.dumps(approved, indent=1, sort_keys=True).encode()
        swapped = json.loads(Path(plan_path).read_text())
        swapped["job_uuid"] = "job-swapped"
        swapped["session"] = "swapped-session"
        swapped_bytes = json.dumps(swapped, indent=1, sort_keys=True).encode()
        fifo = tmp / "plan.fifo"
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
            deadline = time.time() + 15.0
            status = None
            while time.time() < deadline:
                if Path(plan["status_path"]).is_file():
                    try:
                        status = read_status(plan["status_path"])
                    except Exception:
                        status = None
                    if status and status.get("state") == "failed":
                        break
                time.sleep(0.02)
            code, out, err = finish(proc)
            thread.join(timeout=6.0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        report = {
            "driver": str(DRIVER),
            "driver_sha256": sha_file(DRIVER),
            "approved_plan_sha256": sha_bytes(approved_bytes),
            "swapped_plan_sha256": sha_bytes(swapped_bytes),
            "driver_exit": code,
            "status_job_uuid": (status or {}).get("job_uuid"),
            "status_session": (status or {}).get("session"),
            "status_plan_sha256": (status or {}).get("plan_sha256"),
            "approved_document_executed":
                (status or {}).get("plan_sha256") == sha_bytes(approved_bytes)
                and (status or {}).get("job_uuid") == "job-approved",
            "fifo_documents_served": len(served),
            "second_document_served": len(served) > 1,
            "stderr_tail": (err or "").strip().splitlines()[-1:],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["approved_document_executed"] and len(served) == 1 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
