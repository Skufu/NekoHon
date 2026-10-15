# Colab capture session 2026-10-15 — what broke, and the runbook

The first 27B capture session (A100, kit v3). Four real failures, one own-code
bug, one false alarm. Every fix below is **baked into the notebook**
(`reports/teacher-capture-colab-2026-10-15.ipynb`) — this document is the why,
plus the diagnostic ladder for the next time something looks wrong.

## 1. Port 8080 is occupied in the Colab VM

- **Symptom:** `llama-server` exits with `couldn't bind HTTP server socket,
  hostname: 127.0.0.1, port: 8080`; earlier, a *different* symptom from the
  same cause: `HTTP Error 404` from `http://127.0.0.1:8080/v1/chat/completions`
  (Colab's own service answering our route).
- **Cause:** something in the Colab image already listens on 8080. Nothing to
  do with our server.
- **Fix (baked in):** serve and chat on **8000**.
- **Verify:** `!ss -ltnp | grep -E ':(8080|8000)'` before the capture; the
  serve cell prints `health: ...` only when our server owns the port.

## 2. The CUDA plugin silently falls back to CPU (the expensive one)

- **Symptoms:** the Resources panel showed **GPU RAM 0.0 / 40.0 GB** while
  rows took ~1 minute; the server log showed `n_threads = 6` and timings of
  **1.92 tokens/s generation, 13.7 tokens/s prefill** — CPU numbers on an
  idle A100.
- **Cause:** `libggml-cuda.so` needs the NVIDIA *driver* library
  `libcuda.so.1`, which in this Colab image lives in `/usr/lib64-nvidia` and
  is **not** on the default loader path. The dlopen fails and llama.cpp
  continues on CPU without a fatal error — hence "silent".
- **Fix (baked in):** `LD_LIBRARY_PATH="/content/llama:/usr/lib64-nvidia"`
  (`/content/llama` holds the bundled cudart 12.8 / cublas; the driver lib is
  the extra piece).
- **Verify after serve:** Resources shows ~16-17 GB GPU RAM; rows take
  seconds. The money test if in doubt:

```
!cd /content/llama && LD_LIBRARY_PATH=/content/llama:/usr/lib64-nvidia ./llama-server --list-devices
!LD_LIBRARY_PATH=/content/llama:/usr/lib64-nvidia python -c "import ctypes; ctypes.CDLL('/content/llama/libggml-cuda.so'); print('dlopen OK')"
```

- **Diagnostic ladder (do not skip steps):**
  1. `!nvidia-smi` — is the GPU there at all, and is any process using it?
  2. Resources panel / `nvidia-smi` — GPU RAM 0.0 while rows are slow ⇒ this
     failure.
  3. `--list-devices` prints `(none)` ⇒ no accelerator backend loaded.
  4. The `ctypes.CDLL` line above names the missing library directly — that is
     what identified `libcuda.so.1` in one shot.
  5. `!find /usr -name "libcuda.so*"` — locate the driver lib; add its
     directory to `LD_LIBRARY_PATH`.

## 3. The upload widget dies on a browser reconnect

- **Symptom:** `Upload widget is only available when the cell has been
  executed in the current browser session. Please rerun this cell to enable.`
- **Fix:** re-run the cell. If the files are already in `/content`, comment
  `_files.upload()` out first (the cell reads fixed paths).
- **Trap:** Colab **never overwrites** on upload — a re-upload lands as
  `teacher-capture-2026-10-15 (1).jsonl` while the cell keeps reading the
  original path. So "re-uploading to update the file" does nothing; delete the
  old file or comment the upload line.

## 4. "Resuming execution" is not a restart, and the old server keeps the port

- After a browser reconnect the runtime (and any running server) can still be
  alive; a new serve cell then fails to bind because the old process holds
  8000. **Fix:** `!pkill -f llama-server` before re-running the serve cell.
- After a *true* runtime restart, re-run cells 1 → 4 → 5 → 6 in order:
  `chat()` is defined in cell 5, and the capture cell needs it.
- Quick state check in one line: `!curl -s http://127.0.0.1:8000/health`.

## 5. Own-code bug: empty `q` labels crashed the pre-gate print

- **Symptom:** `TypeError: 'NoneType' object is not subscriptable` at the
  pre-gate's print line, after the generation had already succeeded.
- **Cause:** the capture builder read `row.meta.meta` from the old training
  file; the file stores `row.meta` — so all 328 recapture rows had `q=None`.
- **Fix:** builder corrected and the capture file rebuilt (labels only — the
  prompts were byte-identical, so the live session needed no re-upload); the
  print now falls back to the row id
  (`probes/patch-teacher-kit-2026-10-15c.py`).

## 6. False alarm: the "cold start"

Model load happens **inside the serve cell** (before `/health` passes) — the
first slow thing you see. The *first request* then adds a CUDA graph warm-up
(10-30 s). Rows after that are seconds. So: silence in cell 4 while loading is
expected; a minute-per-row in cell 5 is failure #2, not a cold start.

## 7. The capture mixed two prompt seams (found in the results)

- **Symptom:** the recapture rows came back quote-first 274/274 (perfect);
the new-form rows came back as prose with inline tags — 86 of 96 without any
quoted sentence.
- **Cause:** the recapture rows re-used the old dataset's prompts, which are
**ask-shaped** (ask system prompt + "Copy one sentence from a passage. Do not
reword it."). The new forms were built through `answer.respond` —
**answer-shaped** ("Answer the question directly, in your own words."). Same
teacher, two instruction sets, two output styles.
- **Why it matters:** training targets must be one shape. The `[Ch. ` retry
prefill and the existing 328-row base both assume quote-first; mixing styles
on exactly the deficit shapes (bare/causal/flip) undercuts the retry.
- **Fix:** rebuild the new forms through the ask seam and capture again —
`probes/build-teacher-capture-ask-2026-10-15.py` ->
`data/finetune/teacher-capture-ask-2026-10-15.jsonl` (187 rows) -> a short
second Colab pass (~5 min; weights cached). The first results file is kept
as evidence; the recapture half is reused as-is.
- **Lesson (now in the checklist):** before uploading a capture file, verify
**every** row's user-message tail is the ask reminder and every system prompt
carries "quote that passage". One seam per capture.

## Checklist for the next session (paste-block for cell 0)

- [ ] Runtime is A100/L4 (Runtime → Manage sessions).
- [ ] After serve: `health:` JSON printed **and** GPU RAM ~16 GB.
- [ ] `--list-devices` lists `CUDA0` (optional, when in doubt).
- [ ] Port free: our server owns 8000 (not 8080 — occupied).
- [ ] Files already in `/content`? Comment `_files.upload()` out.
- [ ] Pre-gate `PASS` before starting the capture; rows every few seconds; if
      a row takes >30 s, stop and run the ladder in §2.
- [ ] Before uploading a capture file: every row's user tail is the **ask**
      reminder ("Copy one sentence from a passage...") and every system
      prompt says "quote that passage" — one seam per capture (§7).

Recorded the same day in `AGENTS.md` (state bullet) and in the notebook's
cell 0. The capture run itself was in flight when this was written; its
timings land in the results file.
