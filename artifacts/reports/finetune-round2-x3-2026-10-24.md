# Finetune round 2 — 844-row corpus, validation split, 2 vs 3 epochs

2026-10-24. Follow-up to `qwen35-swap-2026-10-24.md`. The first Qwen3.5 run
used the 417-row x2f corpus, which is fde-only and shares 109 rows with the
3B's corpus. The 3B was trained on 844 rows across six domains. This run gives
the 2B the same food, holds out 10% by question, and measures overfitting.

## Setup

| | |
|---|---|
| data | `quote-refuse-2026-10-17.train-x3.jsonl`, sha256 `fd06f9818114837b…` |
| rows | 844 (137 refusals, 790 distinct questions) |
| split | 10% by question: 760 train / 84 valid (13 refusals in valid) |
| recipe | unchanged: r=16/alpha=32, 7 projections, lr 2e-4, seed 3407, responses-only, max 4096 |
| VM | Colab L4, ~1.7 compute units for both runs |
| exports | `nekohon_q35_2b_x3` (3 epochs), `nekohon_q35_2b_x3_2e` (2 epochs) |

## Validation loss

| run | epoch 1 | epoch 2 | epoch 3 |
|---|---:|---:|---:|
| 3 epochs | 0.4754 | **0.4643** | 0.5438 |
| 2 epochs | 0.4785 | 0.4830 | — |

**The 3-epoch run overfits at epoch 3**: train loss 0.066, validation rises
0.079 from epoch 2. Stopping at 2 epochs gives a near-flat curve (+0.0045).

Caveat, stated so the two rows are not read as one curve: `lr_scheduler_type`
is linear over total steps, so the 2-epoch run decays the learning rate twice
as fast. Its epoch-1 and epoch-2 values are not the same points as the 3-epoch
run's. Within each run the trend is what matters, and both say "stop at 2".

The theoretical best checkpoint was the 3-epoch run's epoch 2 (0.4643), but it
was not saved (`save_strategy="no"`). The 2-epoch export is the reproducible
best available.

## Gates

Same rules as `test-fairness-2026-10-24.md`. All in-process or over HTTP on the
same box, one answerer resident.

| gate | `nekohon_x3` 3B | `q35` 417/5e | `x3` 844/3e | `x3_2e` 844/2e |
|---|---:|---:|---:|---:|
| step2 battery, ask | 9/10 | 10/10 | 10/10* | **10/10** |
| step2 battery, answer | 10/10 | 10/10 | 10/10* | **10/10** |
| hard bench | 59/60 | 59/60 | 59/60 | **59/60** |
| adrian | 31/35 | 31/35 | 31/35 | **32/35** |
| sealed hold-out | **28/30** | 25/30 | 26/30 | **27/30** |
| p50 latency | 0.65 s | 0.65 s | 0.65 s | 0.65 s |
| resident | 2,059 MiB | 1,320 MiB | 1,320 MiB | 1,320 MiB |

\* measured before the retired typo item was replaced; the failing item was the
test's fault, not the model's (next section). Not re-run.

Reading: more data moved sealed from 25 to 27 and adrian from 31 to 32, with
every other gate tied. The 3B still leads the sealed unseen set by 1.

## The 14-second latency was not the model

The 3-epoch model first showed a 4.78 s mean with 21 of 60 asks at ~14 s. Three
models were resident on one 8 GB card (`q35`, `x3`, `x3_3e`), so Ollama was
evicting and reloading. With only the model under test loaded:

| | crowded | isolated |
|---|---:|---:|
| mean | 4.78 s | 0.62 s |
| p50 | 0.70 s | 0.65 s |
| p90 | 13.99 s | 0.82 s |
| max | 15.42 s | 2.45 s |

The 2-epoch export measured the same way: mean 0.66 s, p50 0.65 s, p90 0.91 s.
Operational rule: `ollama stop` the other answerers before any latency run.

## Test defect retired: the "ET" typo

The battery's second typo was "What happens to data after it is extracted in
ET?". The engine repairs a word only when it is absent from the book, and "et"
is present 12 times in "et al". So no repair fired, and the item passed only
when retrieval happened to land on a passage containing "extracted".

The 2-epoch model failed it twice, deterministically, by quoting a business-logic
passage that answers "what happens after extraction" without using that word.
That is a test defect, not a model failure.

Retired in `datasets/battery-pins.json` with the reason, and replaced by:

`What is ingestoin?` -> term `ingestion`, pin `ch07-002`.

Verified: "ingestoin" appears in 0 of 1,042 chunks, repairs to "ingestion", and
passes 2/2 on both `q35` and `x3_2e`.

## Decision

`nekohon_q35_2b_x3_2e` is the default. It dominates the 417-row run on both
held-out surfaces and ties it everywhere else, at the same footprint.

Reverts, in order of preference: `ANSWER_MODEL=nekohon_q35_2b` (417-row run),
`ANSWER_MODEL=nekohon_x3` (3B, still best on the sealed set).

## Artifacts

- `artifacts/colab/qwen35_train_v2.py` — training script (env: `FORCE_EPOCHS`,
  `EXPORT_NAME`)
- `artifacts/evidence/finetune-q35-x3/epoch-table.json` (3e),
  `epoch-table-2e.json` (2e)
- `models/nekohon_q35_2b_x3/Modelfile`, `models/nekohon_q35_2b_x3_2e/Modelfile`
- GGUFs: `data/models/nekohon_q35_2b_x3*/nekohon_q35_2b_x3*_2e.Q4_K_M.gguf`
  (gitignored, 1,312,164,768 bytes each)
