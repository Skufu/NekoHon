#!/usr/bin/env python3
"""Probe 1: real driver COMPLETE status -> current public watchdog.

The driver is the real OS process. The watchdog is the current source. The
fake CLI is transport only: it reads the real status bytes and copies the real
artifact bytes to the watchdog's artifact dir.
"""

import json
import sys

import probe_common as C


def main():
    report = {"environment": C.environment(), "checks": []}
    tmp = C.new_tmp("complete")
    try:
        plan, plan_path = C.build_plan(tmp, chunk_size=256)
        proc = C.start(plan_path)
        awaiting = C.wait_status(plan["status_path"],
                                 lambda s: s.get("phase") == "awaiting_approval")
        report["checks"].append({
            "name": "handoff_status_is_real_and_current_watchdog_accepts",
            "phase": awaiting["phase"], "state": awaiting["state"],
            "train_calls_before_approval":
                len((tmp / "train-count").read_text().splitlines())
                if (tmp / "train-count").exists() else 0,
        })
        WT, watch, _cli = C.make_watchdog(plan, tmp / "watch-handoff",
                                         until_preflight=True)
        code = watch.run()
        handoff_events = [json.loads(line) for line in
                          (tmp / "watch-handoff" / "events.jsonl").read_text().splitlines()]
        downloaded = sorted(p.name for p in (tmp / "watch-handoff" / "artifacts").iterdir())
        report["checks"].append({
            "name": "handoff_watchdog_exit_and_downloads",
            "exit": code, "downloaded": downloaded,
            "events": [e["kind"] for e in handoff_events],
            "preflight_valid": watch._preflight_valid(awaiting),
        })

        C.write_approval(plan, awaiting)
        code, out, err = C.finish(proc)
        status = C.read_json(plan["status_path"])
        report["checks"].append({
            "name": "driver_terminal_complete",
            "driver_exit": code, "state": status.get("state"),
            "child_exit_code": status.get("child_exit_code"),
            "artifacts_complete": status.get("artifacts_complete"),
            "stdout_tail": (out or "").strip().splitlines()[-1:] ,
            "stderr_tail": (err or "").strip().splitlines()[-1:],
        })

        # Verify the driver's own chunk contract on the real bytes.
        by_archive = {}
        for item in status["artifacts"]:
            by_archive.setdefault(item["archive_sha256"], []).append(item)
        chunk_facts = []
        for archive_sha, items in by_archive.items():
            items = sorted(items, key=lambda i: i["chunk_index"])
            joined = b"".join(C.Path(i["path"]).read_bytes() for i in items)
            chunk_facts.append({
                "label": items[0]["label"], "format": items[0]["format"],
                "chunks": len(items),
                "max_chunk_bytes": max(i["bytes"] for i in items),
                "chunk_limit_respected": max(i["bytes"] for i in items) <= plan["chunk_size_bytes"],
                "reassembles": C.sha_bytes(joined) == archive_sha,
                "indexes_contiguous": [i["chunk_index"] for i in items]
                    == list(range(1, len(items) + 1)),
                "local_names_unique": len({i["local_name"] for i in items}) == len(items),
            })
        report["checks"].append({"name": "complete_chunk_contract",
                                 "status_artifact_paths_len": len(status.get("artifact_paths", [])),
                                 "status_report_paths_len": len(status.get("report_paths", [])),
                                 "chunks": chunk_facts})

        # The actual observation: the current watchdog against this real status.
        WT2, watch2, _ = C.make_watchdog(plan, tmp / "watch-complete")
        models = [it for it in watch2._artifact_items(status)
                  if it.get("required") and watch2._is_model_artifact(it, status)]
        report["checks"].append({
            "name": "current_watchdog_on_real_complete_status",
            "complete_valid": watch2._complete_valid(status),
            "detected_model_items": len(models),
            "first_items": [(it["kind"], C.Path(it["path"]).name)
                            for it in watch2._artifact_items(status)[:4]],
            "watchdog_exit": C.make_watchdog(plan, tmp / "watch-complete-run")[1].run(),
        })

        # Counterfactual: identical real bytes, a status FILE that only loses
        # the top-level artifact_paths/report_paths keys (so artifacts[].kind
        # describes each path first) and adds the root log hash the watcher
        # demands. Not driver output; it isolates the two contract causes.
        variant = dict(status)
        variant.pop("artifact_paths", None)
        variant.pop("report_paths", None)
        variant["artifact_hashes"] = dict(status.get("artifact_hashes") or {})
        variant["artifact_hashes"][status["log_path"]] = C.sha_file(status["log_path"])
        variant_path = C.Path(plan["job_dir"]) / "counterfactual-status.json"
        C.write(variant_path, json.dumps(variant, indent=1, sort_keys=True))
        WT3, watch3, _ = C.make_watchdog(plan, tmp / "watch-variant")
        # point the same fake transport at the counterfactual file
        watch3.cli.status_path = variant_path
        report["checks"].append({
            "name": "counterfactual_status_shape_acceptance",
            "artifact_kinds_first": [(it["kind"], C.Path(it["path"]).name)
                                     for it in watch3._artifact_items(variant)[:3]],
            "complete_valid": watch3._complete_valid(variant),
            "watchdog_exit": watch3.run(),
            "downloaded": sorted(p.name for p in (tmp / "watch-variant" / "artifacts").iterdir()),
        })
        report["status_path"] = plan["status_path"]
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
