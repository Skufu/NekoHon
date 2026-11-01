#!/usr/bin/env python3
"""Probe 2: real driver FAILED statuses -> current public watchdog.

Covers an early failure with no preflight report (package/install/freeze),
a preflight failure, a post-train failure that must salvage checkpoints, and a
train that exits 0 while required artifacts are missing.
"""

import json
import sys
import zipfile
from pathlib import Path

import probe_common as C


def run_case(label, **kwargs):
    tmp = C.new_tmp(label)
    plan, plan_path = C.build_plan(tmp, **kwargs)
    proc = C.start(plan_path)
    try:
        state = C.wait_status(
            plan["status_path"],
            lambda s: s.get("phase") == "awaiting_approval"
            or s.get("state") in ("failed", "complete"),
            timeout=20.0)
        if state.get("phase") == "awaiting_approval":
            C.write_approval(plan, state)
        code, out, err = C.finish(proc, timeout=30.0)
    finally:
        if proc.poll() is None:
            C.kill(proc)
    status = C.read_json(plan["status_path"])
    failure = C.read_json(status["failure_path"]) if status.get("failure_path") else {}
    WT, watch, cli = C.make_watchdog(plan, tmp / "watch")
    result = watch.poll_once()
    run_exit = C.make_watchdog(plan, tmp / "watch-run")[1].run()
    art_dir = tmp / "watch-run" / "artifacts"
    downloaded = sorted(p.name for p in art_dir.iterdir()) if art_dir.is_dir() else []
    events = [json.loads(line)["kind"] for line in
              (tmp / "watch-run" / "events.jsonl").read_text().splitlines()]
    report = {
        "label": label,
        "driver_exit": code,
        "state": status.get("state"),
        "child_exit_code": status.get("child_exit_code"),
        "failure_stage": failure.get("stage"),
        "failure_exit": failure.get("exit_code"),
        "preflight_report_exists": Path(plan["paths"]["preflight_report"]).exists(),
        "train_calls": len((tmp / "train-count").read_text().splitlines())
                       if (tmp / "train-count").exists() else 0,
        "download_manifest_exists": Path(plan["paths"]["download_manifest"]).exists(),
        "manifest_missing": (C.read_json(plan["paths"]["download_manifest"])["missing"]
                             if Path(plan["paths"]["download_manifest"]).exists() else None),
        "status_report_paths": status.get("report_paths"),
        "status_log_paths": status.get("log_artifact_paths"),
        "all_status_hashes_ok": all(
            C.sha_file(p) == status["artifact_hashes"][p]
            for p in (status.get("report_paths") or []) if Path(p).is_file()),
        "watchdog_poll_terminal": result.get("terminal"),
        "watchdog_poll_state": result.get("state"),
        "watchdog_run_exit": run_exit,
        "watchdog_events": events,
        "downloaded": downloaded,
        "model_artifacts_in_status": len(status.get("artifact_paths") or []),
        "checkpoints_zip_present": any(
            item["label"] == "checkpoint" for item in status.get("artifacts") or []),
    }
    checkpoints = [item for item in status.get("artifacts") or []
                   if item["label"] == "checkpoint"]
    if checkpoints:
        parts = sorted(checkpoints, key=lambda i: i["chunk_index"])
        joined = b"".join(Path(p["path"]).read_bytes() for p in parts)
        report["checkpoints_reassemble"] = C.sha_bytes(joined) == checkpoints[0]["archive_sha256"]
        downloaded_parts = [art_dir / p["local_name"] for p in parts]
        report["checkpoints_downloaded"] = all(p.is_file() for p in downloaded_parts)
        if report["checkpoints_downloaded"]:
            rebuilt = b"".join(p.read_bytes() for p in downloaded_parts)
            report["checkpoints_download_sha_ok"] = (
                C.sha_bytes(rebuilt) == checkpoints[0]["archive_sha256"])
            try:
                report["checkpoints_zip_members"] = zipfile.ZipFile(
                    __import__("io").BytesIO(rebuilt)).namelist()
            except zipfile.BadZipFile:
                report["checkpoints_zip_members"] = "BAD_ZIP"
    C.cleanup(tmp)
    return report


def main():
    report = {"environment": C.environment(), "cases": []}
    report["cases"].append(run_case("package_fail", package_exit=1))
    report["cases"].append(run_case("install_fail", install_exit=1))
    report["cases"].append(run_case("freeze_fail", freeze_exit=1))
    report["cases"].append(run_case("preflight_fail", preflight_exit=1))
    report["cases"].append(run_case("train_fail", train_exit=1))
    report["cases"].append(run_case("train_ok_missing_report", train_skip_report=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
