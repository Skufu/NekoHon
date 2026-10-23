# Highlight finetune x2f — build, tests, verdict (2026-10-16)

**Verdict: not adopted.** `smallbook_x2f` is better at the new highlight job
(13/24 vs 7/24 held-out full pass) but regresses one standing coherence
question (Codd refused 5/5 draws, x2d answers it) and fails the answer-mode
battery. `smallbook_x2d` stays the default. x2f, its LoRA, and the run log
stay on disk as evidence.

## What was trained

- Train file: `data/finetune/quote-refuse-2026-10-16.train-x2f.jsonl`
  — 417 rows = x2d's 328 rows + **72 highlight rows** + refusal oversampling
  to hold the refusal share at 17% (71/417).
- The 72 highlight rows: `data/finetune/highlight-addon-2026-10-16.jsonl` /
  `artifacts/datasets/highlight-train-2026-10-16.jsonl` (built by
  `artifacts/probes/build-highlight-golden-2026-10-16.py`, seed 20261016).
  Each row: the reader marks 1–3 words; `answer.highlight_query` is the
  question; the pinned chunk leads the shown passages; the completion quotes
  one sentence from that chunk and repeats it. No invented gloss.
- Held-out golden: `artifacts/datasets/highlight-golden-2026-10-16.jsonl`
  (24 rows, disjoint chunks, never trained). Pinned by
  `tests/test_highlight_golden.py` (11 tests green).
- Not trained: sealed forms (0 near-matches), the 27-row owner sample.

## The run

- Colab A100, unsloth 2026.10.5 / transformers 5.17.0, 5 epochs (derived:
  1968/417), 265 steps, final loss 0.010, 579 s.
- Rows asserted on load and after responses-only prep (truncation canary);
  stop-check sane on an answer row and a refusal row.
- Artefacts: `data/models/smallbook_x2f/{smallbook_x2f_gguf.zip,
  smallbook_x2f_lora.zip, run-log-smallbook_x2f.json}`; data sha
  `2f1b387a…`, gguf sha `f0bd38d4…`. Imported as Ollama tag
  `smallbook_x2f` (Q4_K_M, 1.9 GB). Colab session stopped after download.

## Measured, both models, same day, same code

### Highlight golden (24 held-out rows, in-process `answer.explain`)

| model | full pass | pin cited | quote verbatim | refused |
| --- | --- | --- | --- | --- |
| `smallbook_x2d` | 7/24 | 9/24 | 9/24 | 5 |
| `smallbook_x2f` | **13/24** | 15/24 | 15/24 | 3 |

Evidence: `artifacts/evidence/highlight-golden/probe-highlight-2026-10-16.model-smallbook_{x2d,x2f}.{json,log}`.

### Battery (HTTP :8000, one engine each, `start-engine.bat` / `start-engine-x2f bat`)

| mode | x2d | x2f |
| --- | --- | --- |
| ask | PASS (9/10 pass; one chunk pin miss on the insert-only question) | PASS (9/10, same single pin miss) |
| answer | PASS (10/10 pass, coherence PASS) | **FAIL — coherence: `Codd introduced the idea of what` refused** |

Evidence: `artifacts/evidence/step2-battery/step2-battery{,-answer}-x2d-2026-10-16.{json,log}` and `…-x2f-2026-10-16.{json,log}`.

### The regression, isolated

- `Codd introduced the idea of what` — x2f refuses in answer and ask modes,
  5/5 draws (`refused: true`, exact sentence); passage ch08-051 is shown
  first-in-list and is what x2d quotes. The question is in both training
  files (as `next codd introduced the idea of what`, answered).
- Mechanism: not isolated. Candidates: the 72 highlight rows dilute the
  fragment-continuation class; the refusal oversampling (17 added refusal
  copies) sharpens the refusal boundary; both runs are single-seed.
- This is a training-data composition issue, not an engine bug: the engine
  fix for this class (a quote the page holds is accepted) landed earlier and
  x2d passes it.

## What this means for the plan

- Keep `smallbook_x2d` as the default (`prompt.ANSWER_MODEL` unchanged).
- x2f is the first evidence that the highlight class moves with training
  (7 -> 13 full pass). The next build should train it again with the Codd
  regression fixed: likely fewer/weighted highlight rows, no refusal
  oversampling, and/or the Codd class re-added explicitly.
- The engine-side highlight fixes (heading passthrough in `web/`,
  versus-form rewrite, list lead-in expansion, half-covered comparison)
  stand on their own and are unaffected.

## Revert

`ANSWER_MODEL=smallbook_x2d` (default, nothing to undo). To try x2f:
`ANSWER_MODEL=smallbook_x2f` before the engine start; restart the engine
after. Delete `smallbook_x2f` from Ollama (`ollama rm smallbook_x2f`) when
the build is superseded.
