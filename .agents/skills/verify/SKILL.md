---
name: verify
description: Run after every cleanup change and before every commit on this repo. Offline gate, behavior cassette, optional live battery and Chrome smoke.
---

# verify

Run the gates in order. Stop at the first red one and read "How to read a failure".

## 1. Offline gate (every change)

| Command | Expected |
|---|---|
| `python3 -m unittest discover -s tests` | `OK` |
| `python3 -m unittest tests.test_generalization tests.test_query_understanding` | `OK` |
| `python3 verify_index.py` | clean, exit 0 |
| `cd web && npx tsc --noEmit && npm run build` | exit 0 |
| `python3 artifacts/harnesses/secret-scan.py` | 0 hits |
| `git status --short` | only the files you meant to change |

Never commit `data`, `books` or `web/node_modules` symlinks in a worktree.

## 2. Behavior gate (every engine change)

```
python3 .agents/skills/verify/cassette.py replay
```

Exit 0 and `cassette: N cases identical` means the engine returns byte-identical
responses for the same model and embedder outputs. It runs in-process, needs no
Ollama and no server, and takes seconds.

- `record` (needs live Ollama; run once on an untouched engine): writes
  `data/verify/cassette.json` and `data/verify/timing-before.json`.
- `timing --out PATH`: replays 3 times, writes per-case and total wall time.
- Re-record only when a change is meant to alter prompts or model output; say so
  in the commit message.
- The cassette holds book text. `data/verify/` is gitignored. Never commit it.

## 3. Live gate (orchestrator only, at checkpoints)

1. `PID=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t)`; kill it only if
   `ps -o command= -p $PID` contains `server.py`.
2. `nohup python3 server.py > data/verify/server.log 2>&1 &`
3. Wait for `curl -s 127.0.0.1:8000/health`; confirm the model with
   `curl -s 127.0.0.1:11434/api/ps`.
4. `python3 artifacts/harnesses/step2-battery.py` then
   `BATTERY_MODE=answer python3 artifacts/harnesses/step2-battery.py`. Expect PASS.
   The multicloud cold-run flake: re-run once; only a repeat counts as red.
5. The battery overwrites tracked evidence under `artifacts/evidence/step2-battery/`.
   Restore: `git checkout -- artifacts/evidence`, unless updating them is the task.

## 4. Chrome smoke (optional, orchestrator)

Open http://localhost:3100. The library lists the books from `/health`. Open a
book, select a sentence, press Explain: the answer streams with a `[Ch. N]`
citation. Click the citation: the reader scrolls. Reload: the highlight persists.
If Chrome is not connected, log `SKIPPED: chrome`. Never fake a pass.

## How to read a failure

- `MISS`, exit 2: the engine now sends a model or embedder request the cassette
  never saw. The output prints the new request and the nearest recorded one.
  A prompt, a retrieval input or a call order changed. If intended, re-record.
- `DIFF`, exit 1: every request matched, but the response differs. The unified
  diff shows recorded vs replayed. This is a post-processing change (parsing,
  citations, glosses, figures). Decide if it is intended; if not, revert.
- Exit 0 after a refactor means behavior is preserved for the recorded cases.
  It does not cover paths outside them (imports, other books, UI).
