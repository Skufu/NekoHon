# Finetune data prep — quote-or-refuse dataset (2026-10-13)

Builder: `artifacts/build-finetune-data-2026-10-13.py`. Teacher qwen2.5:7b
at temperature 0, captured through the shipped inference seam
(`canonical_query` -> `retrieval_context` -> `user_message(SYSTEM)`), so
every row is exactly what the small model will see: system = the shipped
SYSTEM prompt, user = the exact user message, assistant = the target.

## Final numbers (191 questions in)

- 185 rows kept before over-sampling: gold 80 / silver 76 / refusal 29;
  the train split's 27 refusal questions are then repeated x3 (54 extra
  copies) — 13 refusal cards among 113 answer cards taught the v2 models
  "always quote something". 239 rows total.
- **Split: train 194 / bench 45.**
  - Train file: `data/finetune/quote-refuse-2026-10-13.train.jsonl` — the
    only file Colab gets.
  - Bench file: `data/finetune/quote-refuse-2026-10-13.bench.jsonl` — the
    exam; never trained on.
  - Bench rule: all `eval-*` and class-variant rows, plus sweep questions
    that restate a bench topic (caught by pattern: watermark x4 incl. the
    typo, mesh; MAD deduped against the eval row).
- Refusal mining v2: pool reworked to 28 (obvious exotica plus book-adjacent
  near-misses; the first pass's five answered-from-passing-mentions
  candidates are excluded); 27 refused and kept (train, x3 -> 81 targets),
  **1 rejected**: "What is the best programming language?" answered from
  ch01-039.
- Gloss: teacher supplied 30; 126 synthesized with `PARAPHRASE_SYSTEM`
  (the ~80% gloss-drought). Refusals are exactly `Not in this book.`
- 6 rejects total: 1 wrong-chunk, 4 teacher-refused (book-covered
  questions the ask teacher refuses), 1 answered-when-refusal-expected.
- Independent file checks: train 194 rows / 81 refusals / 0 malformed;
  bench 45 / 2 / 0.

## Schema

Row = `{"messages": [system, user, assistant], "meta": {...}}` — chat
JSONL, directly consumable by Unsloth/Axolotl/TRL `SFTTrainer`. Assistant
target is normalized: `[Ch. N] "verbatim quote"` + one gloss line.
Meta carries question/asked/source/split/tier/pin/cited/canonical_fired/
synthesized_gloss.

## Recipe

`artifacts/finetune-colab-recipe-2026-10-13.md` (plain steps) +
`artifacts/finetune-colab-2026-10-13.ipynb` (the notebook). Colab Pro /
A100 or L4; Unsloth LoRA; export a Q4_K_M GGUF; import into Ollama here
and run the bench against the recorded 7B numbers (batteries, retest,
class variance).

## First checkpoint (v1, `smallbook:latest`) — result 2026-10-13

- Colab run (Qwen2.5-3B-Instruct, 60 steps, full-text loss) -> GGUF
  **1.93 GB** Q4_K_M, imported into Ollama, runs through the real engine.
- Learned: the exact refusal sentence (France refuses correctly) and the
  `[Ch. N] "..."` shape.
- Failed: **stopping** (one call produced 174,181 chars in 354 s, quote
  after quote, never ended), wrong quote selection ("What is a watermark?"
  quoted ch06 disk blocks instead of ch08-039), and a false refusal on MAD
  (in-book question). The in-process bench (`probe-small-ask-2026-10-13.py`)
  timed out on the runaway; not runnable until stopping is fixed.
- Diagnosis: v1 trained on the whole text — the system prompt and the five
  passages sat in the loss, drowning the end-of-answer signal with 126
  worksheets of noise. Notebook v2 fixes this with
  `train_on_responses_only` (answer-only loss), 120 steps, and a
  stop-check cell before export.
- Next: v2 run, then a second candidate (change MODEL_NAME + EXPORT_NAME;
  Qwen3-4B-Instruct-2507 first, Llama-3.2-3B-Instruct optional). The v1
  checkpoint stays in Ollama as a baseline.

## File verification (independent, 2026-10-13)

`probe-finetune-verify-2026-10-13.py` reads both files cold and checks:
JSON shape, the shipped SYSTEM prompt byte-for-byte, the user message
format, every passage block against the index, the assistant target
(refusal exactness; `[Ch. N]` line; the quote under the app's own rule
`_quote_in_passage`; gloss presence), chapter tags against the cited
chunk's index chapter, split correctness, question dedup, and train/bench
overlap.

Result: **PASS, 0 failures** (re-run after the same-evening over-sampling).
train 194 rows (113 answer / 81 refusal), bench 45 (43 / 2), overlap 0;
the x3 refusal copies carry `meta.oversampled` and are the only repeated
questions. 13 quotes (8 train, 5 bench) are
normalized-only under the app rule — every one omits a `(Figure X-Y)` run,
which the app's quote check strips by design; they are faithful to what
the live app displays, not defects. Verified by inspecting the first
failure: the quote "...data science, meaning..." vs the book's "...data
science (Figure 1-4), meaning...".

## v3 checkpoint results (2026-10-13)

Both candidates trained in one L4 session (responses-only, 120 steps),
imported, and benched in-process (`probe-small-ask-2026-10-13.py`):

| model | size | bench | stopping | refusals |
|---|---|---|---|---|
| qwen2.5:7b (baseline) | 4.7 GB | 21/21 | yes | yes |
| `smallbook` (Qwen2.5-3B v2) | 1.9 GB | 19/21 | yes | **lost** (France cited a CIO passage) |
| `smallbook_q3` (Qwen3-4B-2507) | 2.5 GB | 19/21 | yes | **lost** (same) |
| `smallbook-v1` (kept baseline) | 1.9 GB | not runnable (rambled) | no | partial |

- The v2 fix (responses-only + 120 steps) worked: stopping is clean, the
  format holds, and quote selection is right on ~90% — near misses are
  adjacent chunks (insert-only, endpoint, transformations), the same class
  as the 7B's occasional wobble.
- **Regression: the refusal behavior did not survive.** 13 refusal cards
  among 113 answer cards teach "always quote something"; both models answer
  the France canary with a passage. Standard fix applied the same day:
  reworked mining pool + refusal over-sampling x3 (27 questions -> 81
  targets), regenerated train file verified PASS. The notebook does not
  change, only the train file; the next session runs on the regenerated
  file.

## v4 prep — refusal-ratio variants + the loop finding (2026-10-13 night)

- The x3 checkpoints were imported hash-first and benched: **refusals fixed
  on both** (France + iops exact, `probe-small-refuse-2026-10-13.*`), but
  the Qwen2.5-3B checkpoint enters repetition loops on some answer
  questions (source-systems question 1-4/10 draws across temp 0.1-0.3 and
  with penalties; CRUD 4/5 at temp 0), and the 21-pin battery crashed
  mid-run on a different question each pass. Sampler/temperature fixes
  rejected; the app seam stays at temperature 0.
- The Qwen3-4B-2507 checkpoint over-refuses on in-book questions (bench
  2/21 pins) — parked, not a candidate this round.
- Variants built by rerunning the builder at REFUSAL_REPEAT=2 and =1
  (answer rows and teacher unchanged):
  - x2: `quote-refuse-2026-10-13.train-x2.jsonl` — 167 rows (113 answer /
    54 refusal), verifier PASS; also kept as the canonical `train.jsonl`.
  - x1: `quote-refuse-2026-10-13.train-x1.jsonl` — 140 rows (113 answer /
    27 refusal), verifier PASS.
- Notebook v4 trains both in one session; recipe updated; loop evidence in
  `artifacts/finetune-loop-eval-2026-10-13.md`.

## Session results + contamination audit (2026-10-14)

- Trainer env trap found and fixed mid-session: a fresh Unsloth build
  defaulted `max_length=1024` and silently dropped 152/167 rows in the
  first x2 training; the notebook now passes
  `SFTConfig(max_length=max_seq_length)`. Watch the trainer banner
  ("Num examples") every run.
- x2 (167 rows) = the winner: refusals 2/2 exact; battery 18-19/21 over
  four passes; 0 loops in 168 capped draws over all 21 questions. x1 (140
  rows) loops deterministically (insert-only 10/10). x2 is the app's trial
  default (`smallbook_x2`).
- Contamination audit (`artifacts/probe-contamination-2026-10-14.py`): 0
  exact duplicates; 4 near-twins of bench questions in train — data
  ingestion, enterprise architecture, pragmatic-about (x2 bench forms),
  codd (`next codd ...`). Their bench passes are assisted; the Codd FAIL
  stands despite its twin. The rest is shared-word noise.
- Known warts = refusal margins on unmemorized forms (Codd, CRU lowercase,
  DE Lifecycle, Location, ddr4-vs-ddr5 order flip); see
  `x2-trial-2026-10-14.md`.
- Next: x2c (form-perturbation swaps, ~30 rows, counts held) + seed
  control.

## Limits

- Single teacher draw (temp 0; runs deterministic, but one trajectory per
  question).
- 126 synthesized glosses carry the plain register's measured reliability,
  not a fresh audit.
- Class variants are held out entirely (bench), so surface-form training
  leans on the sweep's own style variety (bare / what-is / subject-first).
