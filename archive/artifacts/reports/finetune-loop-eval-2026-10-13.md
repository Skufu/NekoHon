# Loop check — x3-trained smallbook repetition loops (2026-10-13)

Why this exists: the x3-refusal dataset taught refusals (both checkpoints
refuse France and iops exactly), but the Qwen2.5-3B checkpoint now enters
repetition loops on some answer questions instead of emitting the stop
token. The app seam's 120 s client timeout turns a loop into a hard error,
and the 21-pin battery crashed mid-run in three consecutive passes (the
hang moved between questions; the battery writes its log only on
completion, so the crashed passes left no log — the probe's progress lines
named the hanging question each time: CRUD, then watermark, then
source-systems).

Method: `probe-llm-loop-2026-10-13.py` asks one battery question N times
through the app's seam with a `num_predict=300` cap and counts
`done_reason == "length"` draws — a capped loop is a draw that would have
run to the client timeout uncapped. Raw logs:
`probe-llm-loop-2026-10-13.*.log`.

Question "What do source systems provide to the rest of the lifecycle?"
(the question that killed the last bench pass), 10 draws per row:

| sampler | loops |
| --- | --- |
| temp 0.1 | 1/10 |
| temp 0.2 | 4/10 |
| temp 0.3 | 4/10 |
| temp 0.1 + repeat_penalty 1.1, repeat_last_n 64 | 1/10 |
| temp 0.1 + presence_penalty 0.5 | 1/10 |

Spot checks on the two earlier loop questions (5-10 draws):

| setting | loops |
| --- | --- |
| CRUD @ temp 0 | 4/5 |
| watermark @ temp 0 | 0/5 |
| watermark @ temp 0.1 | 0/5 |
| watermark @ temp 0.1 + repeat_penalty 1.3 | 0/3 |

Measured facts beyond the tables:

- Draws at temperature 0 are not byte-identical (288 vs 296 chars on the
  same prompt), so a single draw proves nothing; only rates do.
- Rates swing between passes: the same Q6@0.1 setting measured 6/10 in an
  earlier pass (session output; a repeat-penalty-1.2 Modelfile was active
  then and was later reverted) and 1/10 in the capture above. One rp-1.3
  draw earlier produced a Chinese-tail gloss — penalties distort when they
  do work.
- The loop surface is question- and draw-specific: CRUD loops hard at
  temp 0, is clean at 0.1; watermark is clean in every capture here even
  though a single earlier draw looped.
- Control: the x1-era checkpoint (`smallbook-old`, saved before this
  import) missed the loop on the same prompts (single draws, plus its
  recorded 19/21 bench) — the regression came with the x3 data, not the
  machine or the probe.

Decision: no tested sampler setting removes the loops (rates stay 10-40%
on the affected question), so temperature/penalty hacks are rejected and
the app seam stays at temperature 0. The refusal ratio (x3 = 81 refusal
rows among 194) was the suspect. **Results (2026-10-14): x2 (167 = 113
answer + 54 refusal) = refusals 2/2 exact, battery 18-19/21 over four
passes, 0 loops in 168 capped draws across all 21 questions, insert-only
clean 10/10; x1 (140) loops deterministically (insert-only 10/10).** x2
became the app's trial default. Remaining warts are refusal margins on
unmemorized forms (`x2-trial-2026-10-14.md`); next: x2c perturbation swaps
+ seed control.
