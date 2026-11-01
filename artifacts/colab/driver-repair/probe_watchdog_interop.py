#!/usr/bin/env python3
"""Probe: real driver status shapes -> public watchdog, real bytes only.

The driver runs as a real OS process. The watchdog is imported from the
current tree. The transport double reads the real status file and copies real
artifact bytes; it invents no content. Complete and failed are exercised at
two chunk sizes (chunked and unchunked).
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.test_run_reviewed_job import (  # noqa: E402
    DRIVER, build_plan, finish, public_watchdog, read_status, sha_file, start,
    wait_status, write_approval,
)

WATCHER = ROOT / "artifacts" / "colab" / "watch_training.py"


def run_case(tmp, tag, chunk_size, train_exit=0):
    plan, plan_path = build_plan(tmp / tag, chunk_size=chunk_size,
                                 train_exit=train_exit)
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
    status = read_status(plan["status_path"])
    watch, cli = public_watchdog(status, tmp / (tag + "-watch"))
    complete_valid = watch._complete_valid(status) if train_exit == 0 else None
    exit_code = watch.run()
    expected = set(item["path"] for item in status["artifacts"]
                   if item.get("required", True))
    expected.add(status["download_manifest"])
    verified = True
    for item in status["artifacts"]:
        destination = Path(watch.artifact_dir) / item["local_name"]
        if not destination.is_file() or sha_file(destination) != item["sha256"]:
            verified = False
    return {
        "case": tag,
        "chunk_size_bytes": chunk_size,
        "driver_exit": code,
        "driver_state": status.get("state"),
        "child_exit_code": status.get("child_exit_code"),
        "watchdog_complete_valid": complete_valid,
        "watchdog_exit": exit_code,
        "watchdog_stop_calls": cli.stop_calls,
        "downloads": len(cli.download_calls),
        "downloads_match_explicit_items": sorted(cli.download_calls) == sorted(expected),
        "operational_log_path_downloaded": status["log_path"] in cli.download_calls,
        "chunks_present": any(item.get("chunk_count", 1) > 1
                              for item in status.get("artifacts", [])),
        "all_downloaded_hashes_match": verified,
        "stderr_tail": (err or "").strip().splitlines()[-1:],
    }


def main():
    tmp = Path(tempfile.mkdtemp(prefix="watchdog-interop-probe-"))
    try:
        cases = [
            run_case(tmp, "complete-chunked", 64),
            run_case(tmp, "complete-unchunked", 10_000_000),
            run_case(tmp, "failed-chunked", 64, train_exit=1),
            run_case(tmp, "failed-unchunked", 10_000_000, train_exit=1),
        ]
        report = {
            "driver": str(DRIVER),
            "driver_sha256": sha_file(DRIVER),
            "watcher": str(WATCHER),
            "watcher_sha256": sha_file(WATCHER),
            "python": sys.version.split()[0],
            "cases": cases,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        ok = all(
            case["watchdog_exit"] == (0 if case["child_exit_code"] == 0 else 1)
            and case["downloads_match_explicit_items"]
            and case["all_downloaded_hashes_match"]
            and not (case["chunks_present"] and case["operational_log_path_downloaded"])
            for case in cases
        )
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
