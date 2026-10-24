# Finetune round 3 — +277 teacher rows, measured, not adopted

2026-10-24. Third run of the day. Round 2 (844 rows, 2 epochs) is the shipped
default. This run tests the next lever: more rows, assembled from teacher
output already on disk, with no new 27B capture and no eval leakage.

## Where the rows came from

`probes/build-round3-rows-2026-10-24.py` reads four files and rebuilds rows:

| source | kept |
|---|---:|
| `teacher-capture-2026-10-15.jsonl` + results | 175 |
| `teacher-capture-ask-2026-10-15.jsonl` + results | 48 |
| `quote-refuse-2026-10-16.train-x2g.jsonl` leftovers | 54 |
| **total new** | **277** |

Dropped: 844 duplicates already in x3, 96 answers that were neither a quote nor
the exact refusal, 0 truncated, and 6 eval leaks (the adrian "change data
capture" question plus generic `how` / `why` / `how does that work` fragments
that trip the near-duplicate guard). The leak check runs against hard-bench,
wide-net, the sealed set and every adrian turn.

Corpus: 844 + 277 = **1,121 rows**, split on round 2's exact held-out questions
(76 questions, 103 rows now, 9.2%). Refusals rise from 137 to 263 (23.5%).

## Validation loss

| epoch | train | validation |
|---|---:|---:|
| 1 | 0.4891 | **0.4341** |
| 2 | 0.2116 | 0.4350 |

Flat (+0.0009), and lower than round 2's 0.4785 → 0.4830. The extra rows do help
the loss. The curve still says stop at 1-2 epochs.

## Gates

| gate | round 2 (default) | round 3 |
|---|---:|---:|
| step2 battery, ask | 10/10 | 10/10 |
| step2 battery, answer | 10/10 | 10/10 |
| hard bench | **59/60** | 58/60 |
| adrian | 32/35 | 32/35 |
| sealed hold-out | 27/30 | **28/30** |
| p50 latency | 0.65 s | 0.69 s |

Round 3 ties the 3B on the sealed set, the first time the 2B has done that.

## Why it is not adopted

The hard-bench loss is deterministic, not noise: two runs, same two items.

- `multi_turn_02` "Why do the authors warn against that?" quotes a
  build-vs-buy sentence instead of the cost reasoning (no low-ROI / opportunity
  cost / TCO in the answer).
- `multi_turn_07` "key trade-offs and operational overhead" quotes "ask yourself:
  has this already been created?" instead of overhead / latency / throughput.

Both are wrong-passage choices on a follow-up, not refusals. Shipping +1 on the
sealed set for -1 on multi-turn would be a regression dressed as a win, and the
repo rule is not to ship a gate regression.

## What the failure says about the data

Only **85 of 1,121 rows** carry conversation history (`Earlier in this
conversation...`). Multi-turn behaviour is 7.6% of the corpus, while hard bench
spends 10 of its 60 items on exactly that. More definition rows do not move it.

The next lever is history rows: the same passages and questions, with 2-4 prior
turns, teacher-written in the quote-first shape. That is a new teacher capture,
not a data reshuffle.

## Files

- builder: `artifacts/probes/build-round3-rows-2026-10-24.py`
- corpus: `data/finetune/quote-refuse-2026-10-24.train-r3.jsonl` (gitignored)
- validation list: `data/finetune/val-questions-2026-10-24.txt`
- epoch table: `artifacts/evidence/finetune-q35-x3/epoch-table-r3.json`
- model: `models/nekohon_q35_2b_r3/Modelfile`, tag `nekohon_q35_2b_r3`
  (digest `6ce39fe92a71`), GGUF 1,312,164,768 bytes
- compute: 157.81 units left, 0 assignments active
