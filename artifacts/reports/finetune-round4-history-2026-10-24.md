# Finetune round 4 — history rows from existing teacher answers

2026-10-24. The round-3 finding was that only 7.6% of the corpus carried
conversation history, and the two hard-bench failures were multi-turn follow-ups.
This run adds history rows and measures whether that is the fix.

**It is not, at least not this way.** Not adopted.

## How the rows were built

`probes/build-history-rows-2026-10-24.py`. No new teacher call: every target
answer was already written by Qwen3.8-27B for the same question and passages.
What changes is the prompt, rebuilt byte-for-byte with `answer.user_message`:

- **A, history conditioning, 250 rows.** The anchor row's own question, with
  1-2 earlier turns from the same book in the prompt.
- **B, coreference, 150 rows.** The final question replaces the subject with
  it/that ("What are the main trade-offs of that?", "Why does that matter?").
  The history turn is chosen to share a subject word with the anchor, and the
  template is chosen from the anchor's question aspect, so the existing answer
  still fits.

Guards: anchors in the validation list are skipped, history turns in the
validation list are dropped (62 rows), and 13 rows whose final question matched
an eval item were dropped. Corpus: 1,121 + 400 = **1,521 rows**, 485 (32%) with
history, split on the same 76 held-out questions (1,418 train / 103 valid).

## Validation

| run | epoch | train | validation |
|---|---|---:|---:|
| r4, 2 epochs | 1 | 0.4414 | 0.4325 |
| r4, 2 epochs | 2 | 0.1375 | 0.4597 |
| r4, 1 epoch | 1 | 0.4486 | 0.4483 |

Two epochs overfits hard (+0.027). The 1-epoch export is the one measured.
Its validation (0.4483) is worse than round 3's 0.4350 and better than round 2's
0.4830, but the learning-rate schedule differs per total-step count, so these
are not one curve.

## Gates

| gate | round 2 (default) | round 3 | round 4, 1 epoch |
|---|---:|---:|---:|
| hard bench | 59/60 | 58/60 | **59/60** |
| multi-turn items failed | 0 | 2 | **1** |
| adrian | 32/35 | 32/35 | 32/35 |
| sealed hold-out | 27/30 | **28/30** | 26/30 |
| battery | pass | pass | not run (see below) |

The history rows did what they were meant to: `multi_turn_02` is fixed. They did
not fix `multi_turn_07` ("key trade-offs and operational overhead"), which still
quotes "has this already been created?".

The cost is the sealed set: 26/30, one below the shipped default and two below
round 3. The likely reason is dilution: 400 rows (26% of the corpus) now teach
"ignore the history", and the model's unseen-passage accuracy paid for it.

The battery was not run on this candidate because it is already behind the
default on the held-out set; running it would not change the decision.

## What the failure means

The assembled targets were written for **standalone** questions. Putting a
history in front of them teaches the model to treat history as non-source
(which is correct and visible in the fix to `multi_turn_02`), but it cannot
teach the model to *condition* an answer on the history, because no target
answer ever depended on one.

A real history capture needs the teacher to see the history and write the final
turn with it, in the quote-first shape. That is the 27B kit
(`reports/teacher-capture-colab-2026-10-15.ipynb`), one call per row, roughly
150-250 rows for the multi-turn class. Until that exists, adding more assembled
history rows is not worth compute.

## Files

- builder: `artifacts/probes/build-history-rows-2026-10-24.py`
- history rows: `data/finetune/quote-refuse-2026-10-24.history.jsonl` (400)
- corpus: `data/finetune/quote-refuse-2026-10-24.train-r4.jsonl` (1,521)
- epoch tables: `evidence/finetune-q35-x3/epoch-table-r4-1e.json`
  (the 2-epoch table was printed, not downloaded)
- model: `models/nekohon_q35_2b_r4_1e/Modelfile`, tag `nekohon_q35_2b_r4_1e`,
  GGUF 1,312,164,768 bytes
- compute: sessions stopped after each download
