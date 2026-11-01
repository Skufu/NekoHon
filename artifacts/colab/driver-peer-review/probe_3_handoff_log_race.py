#!/usr/bin/env python3
"""Probe 3: the handoff log hash is a snapshot of a live file.

The driver hashes job.log when it announces awaiting_approval. The parent may
approve before/while the watchdog transfers that snapshot. This probe approves
first, waits until the real driver has appended the train stage, then asks the
current watchdog to download the earlier handoff status.
"""

import json
import sys
import time

import probe_common as C


def main():
    report = {"environment": C.environment(), "checks": []}
    tmp = C.new_tmp("lograce")
    try:
        plan, plan_path = C.build_plan(tmp, chunk_size=256)
        proc = C.start(plan_path)
        awaiting = C.wait_status(plan["status_path"],
                                 lambda s: s.get("phase") == "awaiting_approval")
        log_path = plan["log_path"]
        snapshot = awaiting["artifact_hashes"][log_path]
        report["checks"].append({
            "name": "handoff_snapshot_matches_live_log",
            "snapshot": snapshot, "live": C.sha_file(log_path),
            "phase": awaiting["phase"],
        })

        # Control: a handoff download before approval succeeds.
        WT, control, _ = C.make_watchdog(plan, tmp / "watch-control")
        control_ok = control.download_artifacts(awaiting, require_hash=True)
        events_file = tmp / "watch-control" / "events.jsonl"
        report["checks"].append({"name": "control_download_before_approval",
                                 "ok": control_ok,
                                 "events": ([json.loads(line)["kind"] for line in
                                             events_file.read_text().splitlines()]
                                            if events_file.is_file() else [])})

        C.write_approval(plan, awaiting)
        deadline = time.time() + 15
        while time.time() < deadline:
            text = C.Path(log_path).read_text(errors="replace")
            if "START train" in text:
                break
            time.sleep(0.01)
        live_after = C.sha_file(log_path)
        WT2, race, _ = C.make_watchdog(plan, tmp / "watch-race")
        race_ok = race.download_artifacts(awaiting, require_hash=True)
        race_events = [json.loads(line) for line in
                       (tmp / "watch-race" / "events.jsonl").read_text().splitlines()]
        report["checks"].append({
            "name": "handoff_download_after_approval",
            "ok": race_ok,
            "snapshot": snapshot,
            "live_after_train_start": live_after,
            "snapshot_still_valid": snapshot == live_after,
            "events": [e["kind"] for e in race_events],
            "hash_mismatch_paths": [e.get("path") for e in race_events
                                    if e["kind"] == "hash_mismatch"],
        })

        code, out, err = C.finish(proc, timeout=30.0)
        status = C.read_json(plan["status_path"])
        report["checks"].append({
            "name": "driver_still_completes",
            "driver_exit": code, "state": status.get("state"),
            "terminal_log_hash_matches": (
                all(C.sha_file(p) == status["artifact_hashes"][p]
                    for p in status.get("log_artifact_paths") or [])),
        })
    finally:
        try:
            if 'proc' in locals() and proc.poll() is None:
                C.kill(proc)
        except Exception:
            pass
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
