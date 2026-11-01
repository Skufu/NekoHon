# Independent review — detached driver `run_reviewed_job.py`

Date: 2026-10-30 · Reviewer: independent peer (read-only on source/tests)
Scope: `artifacts/colab/run_reviewed_job.py` + `tests/test_run_reviewed_job.py`,
and their interop with the **current** `artifacts/colab/watch_training.py`.
No source, test, package, data, auth, config, VM, model, or commit changes.

## Reviewed bytes (bind findings to these)

| File | SHA-256 | Size |
|---|---|---|
| `artifacts/colab/run_reviewed_job.py` | `3a3fa72babc313466568c37256331db5af7416069ff945871f1268d3faf29cbb` | 889 lines |
| `tests/test_run_reviewed_job.py` | `393fabb87dc13dddd85d574d9255b273aa4f89a9b1f1d334385dd2c31ad0d572` | 675 lines, 14 tests |
| `artifacts/colab/watch_training.py` | `197bfc783bb9a0c9f7c32d45f0ce1dfdc163d3ab2c65c5b78423af1f46af3565` | interop snapshot only |

Drift note: the task headline said source `89df88e8…`, 854 lines, 13 tests. The
current bytes are `3a3fa72b…`, 889 lines, and the file has 14 tests (13
`DriverTests` + 1 `RealRunnerApprovalTests`). Parent confirmed `3a3fa72b…` is
the frozen current source. None of the findings below were made against
`89df88e8…`; no old receipt binds these bytes.

`python3 -m unittest tests.test_run_reviewed_job -v` ran once: **14 tests, OK,
3.622 s** (Python 3.13.5, this Mac).

## Verdict

**NOT KEEP as-is.** Three reproducible P1 defects, all bounded and fixable;
every other requested acceptance item passes. The suite's 14 tests never feed a
real driver status to the public watchdog, which is why P1-1 is invisible to it.

## P1-1 — The real COMPLETE status is rejected by the current public watchdog

Driver emits `artifact_paths` (model chunks) **first** in
`package_outputs` (`run_reviewed_job.py:697-703`). The watchdog's
`_artifact_items` reads `artifact_paths` before `artifacts`, tags those paths
`kind: "artifact"`, and de-dupes by path, so the later `artifacts[]` entry with
`kind: "model"`/`role: "model"` is discarded
(`watch_training.py:546-571`). `_is_model_artifact` then sees a `.zip` /
`.zip.partNNN` path, no `kind`, no `role`, no `model_format`
(`watch_training.py:337-351`), so `_complete_valid` finds **0 model items** and
refuses the terminal state (`watch_training.py:353-377`). Result: a genuinely
complete job is never downloaded and its VM is never stopped (watchdog exit 4).

Evidence (`probe_1_complete_interop.py`, `probe-1-complete.json`):

```
driver state=complete child_exit_code=0 artifacts_complete=true exit=0
status.artifact_paths=11  status.report_paths=6
watcher complete_valid=false  detected_model_items=0
watcher first items: [("artifact","lora.zip.part001"),
                      ("artifact","merged_16bit.zip.part001"), ...]
watchdog run exit=4  (max_polls, never terminal)
```

This is not an artifact of the probe's tiny chunk size. Re-run with
`chunk_size=10_000_000` (nothing chunked, so each model path is
`lora.zip` / `merged_16bit.zip` / `reviewed_q4_k_m.zip`):
`probe-1-default-chunk-check.log` — `artifact_paths=3`, all `zip`,
`watcher_complete_valid=false`, `watcher_model_items=0`.

Paired cases:
- **Real positive:** the same watchdog accepts the real handoff status
  (`phase=awaiting_approval`, `_preflight_valid=true`) and returns 10 after
  downloading the real report/freeze/log bytes (`probe-1-complete.json`).
- **Counterfactual, same real files:** a status file that drops
  `artifact_paths`/`report_paths` (so `artifacts[].kind` describes each path
  first) validates and the watchdog returns 0, downloading and hash-checking all
  chunks (`complete_valid=true`, `watchdog_exit=0`). Not driver output; it
  isolates the exact contract cause.

Fix surface (author's call): either stop emitting `artifact_paths` (the watcher
already consumes `artifacts[].kind`) or have the watcher tag `artifact_paths`
as model items. Driver-side is the smaller change and is test-safe (no test
asserts `artifact_paths`).

## P1-2 — Extra `sources` entries are silently unverified; an executed gate script can carry any bytes

`closure()` enumerates exactly `("runner", "install", "deps")`
(`run_reviewed_job.py:227-228`), and `load_plan` requires exactly the same
three (`:152-159`). Every other command in `commands` (`guard`, `gate`,
`derive_contract`, `preflight`, `train`) is executed as an opaque argv. A plan
author who declares the executed gate under `sources` (the natural place, next
to `runner`) gets **no verification and no warning**: a declared hash of
`000…0` passes `--check-plan` and the driver still runs that script.

Evidence (`probe_4_plan_closure_scope.py`, `probe-4-closure.json`):

```
declared=000…0 actual=8f17d5fb…  --check-plan exit=0 status=pass
manifest_written_by_check_plan=false          (check-plan does not execute)
run: driver exit=0 state=complete
generated manifest release_id="unverified-gate"   (the unverified script ran)
```

Paired positive: the same wrong-hash plan with the bad hash on
`sources.runner` aborts `--check-plan` with `closure_invalid` (exit 2), so the
pin loop itself works; it is only the un-enumerated names that escape.

Note the asymmetry: **every** non-`generated` entry under `plan.package` *is*
hashed (`run_reviewed_job.py:228-239`), so a plan can work around this by
placing the gate/derive scripts under `package`. If the final plan instead
declares them under `sources`, the closure claim is false. Fix: iterate all of
`plan["sources"]` (require path+sha for each) rather than the hard-coded trio.

## P1-3 — `--plan-sha256` is verified on one read, then a second read is executed (verify-then-use)

`main` reads the plan bytes and compares their SHA to `--plan-sha256`
(`run_reviewed_job.py:736-750`), then calls `load_plan(args.plan)`, which
**re-reads the same path** (`:134-136`). The executed document is the second
read; the caller-approved hash covers the first. `status.plan_sha256`
(`:722`) records the second read, and the public watchdog never checks
`plan_sha256` (`validate_identity` checks only job_uuid/session/source/package,
`watch_training.py:316-325`).

Reproduced deterministically with a FIFO plan path that serves document A on
the first read and document B on the second (`probe_4_plan_closure_scope.py`):

```
approved plan sha = 0e590b02…
driver executed   = job_uuid "job-swapped", session "swapped-session"
status.plan_sha256= 914b004f…  (= sha(document B), not the approved hash)
driver_started_swapped_job = true
```

Threat is a local concurrent writer / symlink-style swap during startup (e.g.
a bootstrap that rewrites the plan after launching the driver), not a remote
attacker. It still defeats "exact plan SHA mandatory", and the watchdog will
not flag it. Fix: parse the already-read `raw_plan` and pass the parsed dict
into `load_plan` (or re-read once and compare the new hash to the expected one
before claiming).

Paired positive: every normal plan run in probes 1/2/4 records
`status.plan_sha256 == sha(plan file)` and the approved `job_uuid`, because the
file is stable across both reads.

## P2 / bounded

1. **Handoff log hash is a live-file snapshot.** `await_approval` hashes
   `job.log` while the handle is open (`run_reviewed_job.py:445-447`) and
   publishes it in `artifact_hashes`. If the parent approves before the
   watchdog transfers, the driver appends `START train` and the transfer fails
   `hash_mismatch`; the watchdog blocks instead of handing off
   (`probe_3_handoff_log_race.py`, `probe-3-lograce.json`:
   snapshot `257e562d…` → live `8024ebe6…`, `download ok=false`). The control
   download before approval succeeds; the terminal log hash is stable and
   verifies. Fix: hand off a sealed copy of the log (or hash only after
   closing/never reuse the log for terminal evidence).
2. **Duplicate train flags bind differently.** `argv_value` returns the first
   `--manifest` (`run_reviewed_job.py:125-131`); argparse (the real runner)
   takes the last. `--check-plan` passes while the executed runner would read
   the last value (`probe-4-closure.json`: driver `out/manifest.json`,
   argparse `decoy-manifest.json`, `same=false`). Parent-authored argv makes
   this unlikely; reject duplicates in the plan check.
3. **Chunked log loses its root hash.** When `job.log` exceeds
   `chunk_size_bytes`, `package_outputs` maps only the chunk paths
   (`run_reviewed_job.py:685`), while the watchdog always injects
   `status["log_path"]` as a required item (`watch_training.py:553-554`). The
   root item then has no hash → `_complete_valid` false even after P1-1 is
   fixed. Not reachable for a normal few-KB log; reachable for a runaway
   >128 MiB log — exactly when handoff matters. Probe 1 at `chunk_size=256`
   shows the missing key; at 10 MB the log is unchunked and the key exists.
4. **Killed supervisor has no terminal state.** "No whole-job deadline" is
   honored (no `timeout=` anywhere; unbounded approval wait), but a SIGKILL /
   VM recycle leaves `state=training` with a dead pid. The watchdog only stops
   on a terminal state, so the session is never stopped automatically. Not a
   driver bug under the no-deadline requirement; needs an external stop rule or
   a dead-PID-nonterminal rule in the watchdog.
5. **Preflight failure can package a passing report.** The fixture preflight
   writes `status:pass` and then exits 1; the driver stops correctly
   (`train_calls=0`) but `package_outputs(complete=False)` still includes that
   report as `preflight-report.json` (probe 2, case `preflight_fail`). The
   failure record disambiguates it; consider marking the report untrusted or
   excluding it on a failed preflight stage.
6. **Approval torn-write burns the single attempt.** The wait reads the file
   once (`:487-496`) and does not retry parse. A non-atomic parent write
   permanently fails the authorized attempt (no retry by policy). Parent should
   write via tmp+rename; a short stable-file retry would make this robust.
7. **Approval has no job/session field.** The real checker binds
   manifest/contract/report bytes/export, not `job_uuid`/`session`. The report
   bytes make replay unlikely, but the status identity is not part of the
   approval. Design note, not a defect found in behavior.

## Acceptance checklist (measured, with probe evidence)

| Item | Result |
|---|---|
| install/freeze/package/preflight failure excludes train | **PASS** — probes 2 (`package_fail`, `install_fail`, `freeze_fail`, `preflight_fail`): driver exit 1, `train_calls=0`, failure stage correct, existing logs/report packaged. Package runs before install; both entry modules import stdlib only at top level (AST check), so that order cannot create a false package failure |
| awaiting_approval handoff is hash-bound | **PARTIAL** — report/freeze/log hashes match at handoff and the current watchdog accepts the real status (exit 10); log is a live-file snapshot → P2-1 |
| real `training_reviewed.verify_approval` binds actual bytes/package; no auto-approval | **PASS** — probe 5: valid passes; same parsed report with different bytes → `approval_report_mismatch`; changed caller package → `approval_manifest_mismatch`; missing reviewer / wrong decision / wrong schema / wrong export / non-passing report / fact drift all refuse. End-to-end driver approval uses the fixture runner (the real runner needs the certified package); driver stayed in `awaiting_approval` with 0 train calls before approval |
| one attempt (O_EXCL) prevents a second optimizer step | **PASS** — `claim_attempt` O_CREAT|O_EXCL before any stage (`:322-335`); `attach_report` returns attached and no train on re-run (test `test_restart_attaches…`, 1 train call). Bad/empty marker fails closed (exit 2) rather than restarting |
| every executed script plan-pinned/closure-verified | **FAIL** — P1-2 (only runner/install/deps; extras ignored) |
| no whole-job deadline | **PASS** — no `timeout=` in the driver; unbounded approval wait; AST test also enforces it. Lifecycle consequence: P2-4 |
| success requires model + report + log, chunked ≤ 128 MiB with reassembly metadata | **PASS** — probe 1: adapter/merged/gguf + run report + log, each part ≤ `chunk_size_bytes`, contiguous `chunk_index`, `archive_sha256`, unique `local_name`, reassembly equals archive hash; `required_missing` refuses a train that exits 0 without its report (probe 2 `train_ok_missing_report`, driver exit 1, artifacts salvaged) |
| failed stage with absent preflight report preserves logs/report and stops | **PASS** — probe 2 package/install/freeze failures: no preflight report exists, driver exit 1, watchdog downloads existing artifacts and verifies stop (`stopped_verified`, exit 1) |
| post-train failure salvages checkpoints before VM stop | **PASS** — probe 2 `train_fail`: `checkpoints.zip` (2 parts) reassembles, downloaded and hash-verified, zip members `checkpoint-1/adapter_model.safetensors`, `checkpoint-1/optimizer.pt`; watchdog stops (exit 1) |
| plan paths/root cwd/source hash relocation | **PASS** — `probe-relative-paths.log`: a plan with relative `job_dir`/`status_path`/`log_path`/`sources`/`package`/`paths` ran from the repo cwd, resolved against the plan's parent (`status` + `job.log` under the plan dir, `--check-plan` exit 0); a byte-identical driver copy in another directory also passes `--check-plan` (content hash, not path) |
| `--check-plan` executes nothing and claims nothing | **PASS** — probe 4: gate output absent, no status file, exit 0; it does read the plan twice → P1-3 |
| changed argv / stale hash aborts | **PASS** — plan-hash mismatch exits 2 before claim (test + probe 4 duplicate/closure); wrong `sources.runner` hash exits 2 |
| status dedupe kind/hash/name for the public watcher | **FAIL on kind** (P1-1); names unique, chunk hashes map by path; root-log hash conditional (P2-3) |

## Not verified

- Actual GPU, CUDA, Unsloth, TRL, tokenizer identity, LoRA attach, `trainer.train()`,
  export (GGUF/merged), or any allocation. The probes use local fixture stage
  scripts; they exercise the driver lifecycle, not the training stack.
- The certified package archive (`91a1137c…`), the real 429/43 manifest/contract,
  and the real `load_package` end to end. The real `verify_approval` was called
  directly (probe 5); the driver's end-to-end approval path used the fixture
  runner that mirrors the shipped API.
- The actual final plan bytes (author still producing them). P1-2/P1-3 are
  plan-shape dependent; P1-1 is independent of the plan.

## Reproduction

All from `artifacts/colab/driver-peer-review/`:

```
python3 probe_1_complete_interop.py      > probe-1-complete.json
python3 probe_2_failed_interop.py        > probe-2-failed.json
python3 probe_3_handoff_log_race.py      > probe-3-lograce.json
python3 probe_4_plan_closure_scope.py    > probe-4-closure.json
python3 probe_5_approval_bytes.py        > probe-5-approval.json
```

`probe-relative-paths.log` holds the relative-path and copied-driver
`--check-plan` check (inline, same helper). `probe-1-default-chunk-check.log`
holds the unchunked complete-status check. `probe_common.py` holds the
fixtures, the real-driver spawn, and the fake transport that reads real status
bytes and copies real artifact bytes. The watchdog is imported from the current
tree; each output records its SHA. Scratch only: no repo source, tests, package,
or data changed.
