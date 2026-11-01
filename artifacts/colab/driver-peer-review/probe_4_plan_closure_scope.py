#!/usr/bin/env python3
"""Probe 4: plan closure scope for scripts the driver actually executes.

The driver's closure loop enumerates exactly ("runner", "install", "deps"). A
plan author who declares another executed script under ``sources`` gets no
verification and no warning. This probe uses real plans and the real driver.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import probe_common as C


def load_driver_module():
    spec = importlib.util.spec_from_file_location("reviewed_job_under_test", str(C.DRIVER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    report = {"environment": C.environment(), "checks": []}
    tmp = C.new_tmp("closure")
    try:
        # (a) extra declared source with a deliberately wrong hash
        plan, plan_path = C.build_plan(tmp / "extra", extra_source=True)
        gate = plan["sources"]["gate"]
        declared_ok = gate["sha256"] == C.sha_file(gate["path"])
        check = subprocess.run(C.driver_argv(plan_path, ["--check-plan"]),
                               cwd=str(C.ROOT), capture_output=True, text=True)
        manifest = Path(plan["package"]["manifest"]["path"])
        report["checks"].append({
            "name": "extra_source_wrong_hash_check_plan",
            "declared_hash_matches_file": declared_ok,
            "declared": gate["sha256"], "actual": C.sha_file(gate["path"]),
            "check_plan_exit": check.returncode,
            "check_plan_status": (json.loads(check.stdout).get("status")
                                  if check.returncode == 0 else None),
            "manifest_written_by_check_plan": manifest.exists(),
        })

        # Then run it end to end and prove the unverified gate script executed.
        proc = C.start(plan_path)
        awaiting = C.wait_status(plan["status_path"],
                                 lambda s: s.get("phase") == "awaiting_approval")
        C.write_approval(plan, awaiting)
        code, out, err = C.finish(proc, timeout=30.0)
        status = C.read_json(plan["status_path"])
        generated = json.loads(manifest.read_text())
        report["checks"].append({
            "name": "extra_source_executed_without_closure",
            "driver_exit": code, "state": status.get("state"),
            "manifest_release_id": generated.get("release_id"),
            "generated_manifest_sha256_matches":
                status.get("generated_manifest_sha256") == C.sha_file(manifest),
        })

        # (b) paired negative: the enumerated pin still works.
        plan_b, plan_b_path = C.build_plan(tmp / "wrongrunner", wrong_runner_hash=True)
        check_b = subprocess.run(C.driver_argv(plan_b_path, ["--check-plan"]),
                                 cwd=str(C.ROOT), capture_output=True, text=True)
        report["checks"].append({
            "name": "enumerated_source_wrong_hash",
            "check_plan_exit": check_b.returncode,
            "check_plan_status": (json.loads(check_b.stdout).get("status")
                                  if check_b.stdout.strip() else None),
        })

        # (c) duplicate --manifest: driver checks the first, argparse uses the last.
        plan_c, plan_c_path = C.build_plan(tmp / "dupflag", gate_generated=False)
        raw = json.loads(Path(plan_c_path).read_text())
        decoy = C.write(tmp / "dupflag" / "decoy-manifest.json", "{}\n")
        raw["commands"]["train"] = list(raw["commands"]["train"]) + ["--manifest", str(decoy)]
        Path(plan_c_path).write_text(json.dumps(raw, indent=1, sort_keys=True))
        module = load_driver_module()
        train = json.loads(Path(plan_c_path).read_text())["commands"]["train"]
        parser = argparse.ArgumentParser(add_help=False)
        for flag in ("--manifest", "--contract", "--preflight-report", "--approval"):
            parser.add_argument(flag)
        parsed = parser.parse_args(train[train.index("--manifest"):])
        check_c = subprocess.run(C.driver_argv(plan_c_path, ["--check-plan"]),
                                 cwd=str(C.ROOT), capture_output=True, text=True)
        report["checks"].append({
            "name": "duplicate_train_flag_binding",
            "driver_first_value": module.argv_value(train, "--manifest"),
            "argparse_last_value": parsed.manifest,
            "same": module.argv_value(train, "--manifest") == parsed.manifest,
            "check_plan_exit": check_c.returncode,
        })

        # (d) verify-then-use: the plan is read twice. A path whose bytes
        # change between the two reads passes the caller hash check and then
        # executes the second document.
        base = tmp / "fifo"
        plan_d, _ = C.build_plan(base, gate_generated=False)
        approved = dict(plan_d)
        approved["job_uuid"] = "job-approved"
        approved_bytes = json.dumps(approved, indent=1, sort_keys=True).encode()
        swapped = dict(plan_d)
        swapped["job_uuid"] = "job-swapped"
        swapped["session"] = "swapped-session"
        swapped_bytes = json.dumps(swapped, indent=1, sort_keys=True).encode()
        fifo = base / "plan.fifo"
        os.mkfifo(str(fifo))

        def serve():
            payloads = [approved_bytes, swapped_bytes]
            for _ in range(3):
                try:
                    with open(fifo, "wb") as handle:
                        handle.write(payloads.pop(0) if payloads else swapped_bytes)
                except Exception:
                    return

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        proc = subprocess.Popen(
            [C.PY, str(C.DRIVER), "--plan", str(fifo),
             "--plan-sha256", C.sha_bytes(approved_bytes)],
            cwd=str(C.ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            state = C.wait_status(plan_d["status_path"],
                                  lambda s: s.get("phase") == "awaiting_approval",
                                  timeout=15.0)
            swapped_status = C.read_json(plan_d["status_path"])
            observed = {
                "job_uuid": swapped_status.get("job_uuid"),
                "session": swapped_status.get("session"),
                "status_plan_sha256": swapped_status.get("plan_sha256"),
                "approved_plan_sha256": C.sha_bytes(approved_bytes),
                "swapped_plan_sha256": C.sha_bytes(swapped_bytes),
                "driver_started_swapped_job":
                    swapped_status.get("plan_sha256") == C.sha_bytes(swapped_bytes),
            }
        finally:
            if proc.poll() is None:
                C.kill(proc)
        report["checks"].append({"name": "plan_fifo_verify_then_use", **observed})
    finally:
        C.cleanup(tmp)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
