# Dims — truncation, renormalisation, centring of stored gemma vectors

**Question.** Can the 768-d vectors already in `data/*.sqlite` rank better without
re-embedding any chunk?

**Method.** Six gemma indexes read read-only over SQLite (`struct` float64, L2 norm
1.0000 at 768-d). 35 answerable rows from
`artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`. Query vectors from
`retrieve.ollama_embed([format_input(GEMMA_EMBEDDER, "query", q)], GEMMA_EMBEDDER)`,
exactly the served query prefix, no other formatting changes. Cosine after
renormalising every truncated/centred vector. Gold rank is the first position of any
gold chunk in the full-chunk ranking; `mean rank` counts a miss as `n_chunks + 1`
(there were no misses outside the top 5 for any configuration, so the found-only mean
is close). Baseline reproduces the protocol number exactly: **19 / 30 / 3.00**.

## Table (35 answerable rows)

| # | configuration | top-1 | top-5 | mean gold rank | changed vs base |
|---|---|---|---|---|---|
| 1 | 768-d normalised (baseline) | 19/35 | 30/35 | 3.00 | — |
| 2 | truncate 512, renormalise | **20/35** | 29/35 | 2.74 | +1 top-1, −1 top-5 |
| 3 | truncate 256, renormalise | **21/35** | **32/35** | **2.40** | +2 top-1, +2 top-5 |
| 4 | centre 768 (subtract corpus mean, renormalise) | **20/35** | 28/35 | 3.46 | +1 top-1, −2 top-5 |
| 5 | centre + truncate 512 | **20/35** | 27/35 | 3.26 | +1 top-1, −3 top-5 |
| 6 | centre + truncate 256 | 17/35 | 31/35 | 2.91 | −2 top-1, +1 top-5 |

Centring was applied per book: the mean vector of that book's 274–1306 chunk vectors
subtracted from docs and query. Configuration 4 is the task's "all-but-the-first-
component" substitute, as specified.

### Truncation curve (renormalised, no centring)

| dims | 768 | 640 | 512 | 448 | 384 | 320 | 256 | 224 | 192 | 128 | 96 | 64 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| top-1 | 19 | 19 | 20 | 20 | 21 | 20 | 21 | **22** | 21 | 17 | 15 | 13 |
| top-5 | 30 | 30 | 29 | 30 | 30 | **32** | **32** | 31 | **32** | 29 | 29 | 25 |
| mean rank | 3.00 | 2.91 | 2.74 | 2.49 | 2.34 | 2.40 | 2.40 | 2.74 | 2.57 | 3.17 | 4.37 | 6.77 |

Everything from 512 to 192 beats the baseline on top-1 by 1–3 rows; 224 is the best
point estimate (22/35). Below 192 it collapses, so this is not "fewer dims = better".

## Where the gain comes from, and what the controls say

Per book, top-1 base → 512 → 256:

| book | rows | base | 512 | 256 |
|---|---|---|---|---|
| fde (index) | 5 | 2 | 2 | 2 |
| ai-agents | 5 | 5 | 5 | 5 |
| ai-engineering | 5 | 3 | 3 | 3 |
| ddia | 5 | 4 | 4 | 4 |
| quantization | 5 | 5 | 5 | 5 |
| mushoku-tensei (fiction) | 10 | **0** | 1 | **2** |

Every top-1 pickup is a fiction row (`fic-ent-dohga` 2→1, `fic-scene-gall-fire` 2→1).
The two top-5 pickups are `tech-ddia-02` (9→3) and `fic-scene-white-place` (7→4); no
row leaves the top 5. The 512 config pays for its one fiction top-1 with
`fic-ent-rudeus` leaving the top 5 (4→6).

Controls, same rows and same query vectors:

- 2000 random **256-dim subsets** (labels never used): top-1 mean 19.25 (sd 1.71,
  range 15–22), top-5 mean 29.02 (sd 1.28, range 27–32). The first 256 dims reach
  21 top-1 (`p = 0.23`) and 32 top-5 (`p = 0.025`); joint `p = 0.007`, but that is
  post-hoc after trying 12 dimensions.
- 1000 of the same random 256-dim subsets, scored on **mean gold rank**: mean 3.995
  (sd 0.822, range 2.229–9.429), i.e. worse than the 768-d baseline's 3.00. Only 3 of
  1000 draws reach 2.40 or better (`p = 0.003`); the first 256 dims sit at the 0.2th
  percentile. So the ranking-depth gain is **not** a random-projection artefact: the
  leading MRL dimensions are where the signal is.
- Paired bootstrap over rows, base vs 256: top-1 delta +2.0, 95% CI 0…+5,
  P(delta>0) = 0.87; top-5 delta +2.0, 95% CI 0…+5, P(delta>0) = 0.87. Both include 0.
- PCA fitted per book on documents only, no labels: 512-d 20/28/3.46, 256-d
  21/28/3.51, 128-d 18/29/3.74 — the same top-1 fluctuation with worse top-5.
- Query embedding is deterministic here (re-embedding one at a time gives max abs
  difference 0.0), so the deltas are not sampling noise in the query encoder.
- Cross-check by DualFusion, independently implemented: the fixed legs reproduce
  exactly (19/30/3.00, 21/32/2.40, 22/31/2.74, nomic 26/31/5.26), and on the fusion
  side the same split appears — mean rank is the robust gain, top-1/top-5 are not.

## Verdict

**Free ordering depth, no reliable free rank-1 or window accuracy.** Truncating the
MRL-trained gemma vectors to 256 dims is the only configuration that moves every
metric the right way (21/35 top-1, 32/35 top-5, mean rank 2.40 vs 19/30/3.00), and the
mean-rank gain is robust: random 256-dim subsets average 3.995 and only 0.3 % reach
2.40 (`p = 0.003`). But the top-1 and top-5 gains are not distinguishable from those
same random subsets (`p = 0.23` / `p = 0.025` post-hoc), and every top-1 pickup is one
of the two fiction rows. Configurations 2, 3, 4 and 5 all beat 19/35 top-1 in point
estimate; the best is 224-d at 22/35, which is out of MRL spec and most likely noise.
Centring subtracts more than it adds.

If the lead wants one cheap change anyway, 256-d is the defensible candidate: it is
MRL-sanctioned for EmbeddingGemma, it cuts vector storage by 3×, it deepens the gold
rank robustly (3.00 → 2.40), and it is the only setting with a top-5 gain (30→32) and
no top-5 loss. It should not be sold as a top-1 improvement on 35 rows, and because
the top-5 set is unchanged beyond two rows it will not visibly change most reader
answers on its own; its value is headroom for reranking or tighter context windows.

## Timing and load

Full six-config sweep: 2.0 s (35 query embeddings 1.5 s, scoring 0.5 s). A rerun of
the query embedding under the four concurrent experiments took 12 s for the same 35
queries, so Ollama was intermittently loaded; every number above uses vectors from
the uncontended 1.5 s run. Files: `Dims.json` (per-row ranks for every config,
per-book counts, rank deltas, curve, controls) and this note.
