# Eval Harness and Reranking Ceiling Audit — 2026-10-23

## What was measured

The hard benchmark and the eval harness scoring rules, to decide whether a
reranker has enough measured headroom to be worth building, before any
reranking work starts.

## Method

Probe: `artifacts/probes/probe-eval-and-rank-2026-10-23.py`, run as
`python artifacts/probes/probe-eval-and-rank-2026-10-23.py`. It measures
key_fact selectivity and dense gold rank over `data/index.json` (1042
chunks). Scoring code was read at its source locations (code facts below);
no scoring code was changed.

## Findings

| # | Finding |
|---|---|
| 1 | Hard bench: 60 items, 6 categories x 10. |
| 2 | 45 of the 60 carry gold_chunks; 15 expect refusal. |
| 3 | 19 of the 45 list more than one gold chunk. |
| 4 | 35 carry a key_fact regex; the 10 explain items carry none. |
| 5 | Key_fact selectivity, measured against the other 44 recorded answers: 18 of 35 patterns match at least one other answer. |
| 6 | Worst pattern: varied_comp_08 (`batch\|streaming\|latency\|interval`) matched 10 other answers; varied_comp_07 matched 9; varied_comp_10 matched 7. |
| 7 | Dense gold rank across the 37 items whose gold chunk exists in `data/index.json`: 19 at rank 1-5, 0 at 6-10, 3 at 11-20, 2 at 21-50, 13 beyond rank 50. |
| 8 | The 10 explain items are handed chunk_id directly and do not test retrieval; excluding them, 27 items search, with 19 of 27 gold in top 5. |
| 9 | Alphanumeric category: 10/10 in top 5. |
| 10 | varied_comparison: 8/10 in top 5, misses at rank 15 and 21. |
| 11 | multi_turn: 1/7 in top 5, gold ranks 11, 30, 84, 240, 271, 586 — but all 27 still cite a gold chunk, because history injection supplies the multi_turn chunk. |
| 12 | Only 2 self-contained items have gold outside top 5: varied_comp_02 at rank 15 and varied_comp_04 at rank 21. |
| 13 | Code fact — `hard-bench.py:288-295`: an item passes on any gold chunk plus a key_fact regex. |
| 14 | Code fact — `hard-bench.py:202-217`: the gloss check is shape only (length at least 35, differs from the quote, 3 banned strings). |
| 15 | Code fact — `adrian-eval.py:114-116`: the adrian check inspects only `citations[0]`. |

## What this means for reranking

A reranker can only move retrieval-rank cases. Findings 9-12 put the
self-contained, retrieval-bound failures at **2 items** (varied_comp_02,
varied_comp_04). The multi_turn misses are not retrieval defects — history
injection already lands the citation, so a reranker does not move them. The
13 gold-beyond-50 ranks live in items that do not search (explain, handed
chunk_id) or are supplied by history, so they are not rerankable either.

**A 2-item ceiling is below the 3-item threshold in
`artifacts/plans/reranking-odp-2026-10-23.md`.** On this measurement, the
reranking opportunity does not justify building a reranker with the current
benchmark; the benchmark would need more retrieval-bound self-contained
failures to make the case.

## What remains unverified

- **Dataset near-duplicate leakage** — whether bench items overlap the
  training data or one another — was not checked.
- **Judge stability was not re-run**; prior stability measurements are
  stale by this date and were not repeated for this audit.
