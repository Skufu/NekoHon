# Reranking bake-off — 2026-10-23

Pre-registered brief: `artifacts/plans/reranking-odp-2026-10-23.md`.
Dataset: `artifacts/datasets/wide-net-2026-10-23.jsonl` (33 hand-written
questions, labels audited the same day). Baseline dense recall@5: 24/33.

## Candidates and cost, measured on this box

| Candidate | Device | 20 pairs | Disk | Host RSS |
| --- | --- | --- | --- | --- |
| Sentence re-scoring (existing embedder) | CPU via Ollama | 2.30 s per question | 0 | +0 |
| `bge-reranker-v2-m3` fp32 | CPU, torch | 11.9-13.4 s | 2,187 MiB | 3,485 MiB |
| `bge-reranker-v2-m3` fp16 | RTX 3060 Ti | **0.20 s warm** (0.81 s first) | 2,187 MiB | 3,242 MiB |

The CPU path is unusable: 12 seconds for 20 pairs. The GPU path is the only
one that fits a product whose whole answer currently takes 0.7-0.9 s. Peak GPU
use is about 1.1 GB of fp16 weights, on a card that already holds 5.3 GB of
Ollama models out of 8 GB.

An int8 ONNX build exists (`onnx-community/bge-reranker-v2-m3-ONNX`, 570 MB,
single file) but it is CPU-only and would land between the two rows above, not
below the GPU one. Not run.

## Recall@5

| Strategy | literal | conversational | vague | all |
| --- | --- | --- | --- | --- |
| Dense baseline | 11/11 | 6/11 | 7/11 | **24/33** |
| Sentence best-match | 11/11 | 4/11 | 6/11 | 21/33 |
| Sentence blend (0.5/0.5) | 11/11 | 6/11 | 8/11 | 25/33 |
| Cross-encoder rerank | 10/11 | 8/11 | 7/11 | 25/33 |
| Rerank, dense #1 kept | 10/11 | 8/11 | 8/11 | **26/33** |
| RRF(dense, rerank) | 10/11 | 6/11 | 8/11 | 24/33 |

Oracle ceiling: **28/33** — the gold chunk is in the top-20 for 28 questions,
so no reranker can exceed 85% on this set.

## By fold (0 = dev, 1-2 sealed)

| Fold | Baseline | Rerank | Rerank + keep #1 |
| --- | --- | --- | --- |
| 0 (n=12) | 8 | 9 | 9 |
| 1 (n=12) | 9 | 10 | 11 |
| 2 (n=9) | 7 | 6 | 6 |

Fold 2 regresses under every reranking variant. On 9 questions that is one
item, but it is the fold that was never looked at.

## Verdict: reject

Gate B in the pre-registered brief requires **at least 3 more gold chunks** at
rank 5. The best variant delivers **2** (24 -> 26), it is a post-hoc guard
added after seeing the losses, and it costs 0.21 s per question, 2.2 GB of
disk, and ~1.1 GB of VRAM competing with the answer model.

Sentence re-scoring also fails: +1 item for 2.3 s per question.

Three questions remain unreachable by any reranker (pool ranks absent): they
need a first-stage fix, not a second stage.

## Side effect that needs a decision

Installing the reranker stack upgraded the global Python environment:
`transformers` 4.46.3 -> 5.20.2, `huggingface-hub` 0.26.2 -> 2.2.0,
`tokenizers` 0.20.3 -> 0.23.3. `fastembed 0.9.0` now reports a conflict. The
engine and tests are stdlib-only and unaffected. Nothing else in this repo
uses those packages; other projects on this machine might. Owner decision
2026-10-23: leave the updates in place.

## Update — the embedder was the real lever

Same day, after the reject. `embeddinggemma-2:270m` (already on disk) was
compared against `nomic-embed-text` on the same 33 questions. The first
attempt had died on a 120 s timeout, not on merit; with a 900 s timeout and a
warm-up call it completed.

| Strategy | @5 | @10 | @20 | vague mean rank |
| --- | --- | --- | --- | --- |
| nomic | 24/33 | 25/33 | 28/33 | 70.3 |
| gemma | 24/33 | **29/33** | 30/33 | **8.5** |
| gemma + cross-encoder rerank | **28/33** | 30/33 | 30/33 | — |

Gemma alone does not improve the top 5, but it moves the right chunk from
mean rank 70 to mean 8.5 on vague questions. Combined with the reranker it
reaches 28/33 (85%), which is the gate.

**But the folds disagree.** Gemma is perfect on fold 2 (9/9) and the reranker
drops it to 7/9. The aggregate gain comes from folds 0 and 1 (6 -> 10 and
9 -> 11), which were visible while tuning. That is the same pattern that sank
the nomic rerank, and it is why this is not recorded as an adopt.

**The cheaper option the numbers point at:** gemma at `@10` is 29/33, one
better than gemma + rerank at `@5`, with no cross-encoder, no 1.1 GB of VRAM,
and no 0.28 s stage. Raising `PASSAGE_LIMIT` from 5 to 10 and switching the
embedder may capture the gain without a second model. That needs an
answer-level run (the bench, not recall), which has not been done.

## Strict key_fact

`hard-bench.py` gained `HARD_BENCH_STRICT=1`: it requires the longest
alternative in the pattern, not any single one. On the recorded x3 answers,
35 of 35 items pass today and 26 of 35 pass under the strict rule. The nine
loose ones are listed by `probes/probe-strict-keyfact-2026-10-23.py`. The flag
is off by default so the recorded run stays comparable.

Note: a smoke run of the harness overwrote the canonical 60-item evidence and
was restored from git in the same session. Re-run the harness with the full
60 items (no `--limit`) before touching that file again.

## Tried and reverted — gemma embedder (2026-10-23)

**Outcome: reverted the same day.** The recall table below is real, but the
gates disagreed: hard bench 60/60 -> 53/60 and adrian 32/35 -> 29/35, both on
citation mismatches. The likely confound, raised by the owner: `nekohon_x3`
was distilled on nomic-retrieved passages, so a gemma retriever plus a
nomic-trained student measures that mismatch, not the embedder. Gemma stays a
candidate that needs either a student finetune on gemma passages or a failure
audit before it can be judged fairly. `DEFAULT_EMBEDDER` is nomic again, and
the three indexes were re-embedded back with
`probes/reembed-gemma-2026-10-23.py nomic-embed-text` (fde 13.1s,
quantization 6.6s, ddia 15.7s). Those index files are not tracked by git, so
re-embedding is the only way back; there is no checkout.

Owner direction: use `embeddinggemma-2:270m-bf16-text` as the embedder. The
57-question set is the one that decided it, because the 33-question version
was too small to separate the two.

| Metric | nomic | gemma |
| --- | --- | --- |
| recall@5 | 38/57 | **43/57** |
| recall@10 | 40/57 | **48/57** |
| recall@20 | 47/57 | **52/57** |
| mean rank | 27.1 | **11.5** |
| any chunk in the right chapter @5 | 50/57 | **54/57** |

Indexes re-embedded in place with `probes/reembed-gemma-2026-10-23.py`:
fde 1042 chunks + 111 figures in 77.9s, quantization 473 + 76 in 37.4s, ddia
1307 + 90 in 98.5s. Both embedders are 768-wide, so `embed_index` would have
skipped every record on a width match; the probe strips the vectors first.

Code changes: `retrieve.DEFAULT_EMBEDDER` is gemma, `NOMIC_EMBEDDER` is named
separately, `document_input` branches on the nomic constant (not the default),
and `hard-bench.py` builds its unseen-book index with the default embedder and
labels it accordingly.

Unit suite: 419 of 421 pass. The two failures are in `web/app/study.css`
(hex colour and a raw shadow), an untracked file from another writer, and they
fail with or without this change.

Latency: a query embed with gemma costs about 0.1s against 0.03s for nomic on
this box; the answer path still dominates.

Revert: restore `DEFAULT_EMBEDDER` and the three index files from git; both
nomic builds are committed and clean.
