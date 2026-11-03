# Dual-embedder fusion (gemma + nomic) — 35 answerable rows

Question: nomic has the better top-1 (26/35), gemma the better window. Can one
query use both? Both index families already exist over the same books and the
same chunk ids (`index_alignment` in the JSON: zero id drift on all six books,
1 042 + 473 + 1 306 + 1 030 + 637 + 274 = 4 762 chunks). Dense only, k=5,
`retrieval-recall-2026-11-02.jsonl`.

Query text is the baseline's: `normalize(question)` plus each model's own query
prefix (`task: search result | query: ` / `search_query: `), embedded with
`retrieve.ollama_embed`, one batch per model for all 35 rows. Scores are cosine;
the z-variants normalise each leg's scores over the whole book, per query, then
combine. Gold rank is the first position of any gold chunk in the full-chunk
ranking; a miss counts as `n_chunks + 1`. Some configurations do miss beyond
rank 5 (nomic's worst is rank 69), so the mean uses that penalty throughout.

Both baselines reproduce exactly (gemma 19/30/3.00, nomic 26/31/5.26), so the
harness agrees with the protocol table.

## Round 1 — both legs at their stored 768-d

| configuration | top-1 | top-5 | mean gold rank | median |
|---|---|---|---|---|
| gemma only | 19/35 | 30/35 | 3.00 | 1 |
| **nomic only** | **26/35** | **31/35** | 5.26 | 1 |
| RRF k=60 | 24/35 | 30/35 | 3.46 | 1 |
| z 0.5 nomic / 0.5 gemma | 24/35 | 31/35 | 3.40 | 1 |
| z 0.6 nomic / 0.4 gemma | 24/35 | 31/35 | 3.77 | 1 |
| z 0.4 nomic / 0.6 gemma | 23/35 | 31/35 | 3.17 | 1 |
| z max | 24/35 | 31/35 | 3.03 | 1 |
| z mean | 24/35 | 31/35 | 3.40 | 1 |

Gains and losses versus nomic only:

- **z max**: gains top-1 on `tech-aieng-01`; loses top-1 on `tech-aieng-05`,
  `fic-ent-eris`, `fic-ent-dohga`. Top-5 unchanged set (31/35).
- **z 0.5/0.5 = z 0.6/0.4 = z mean** (identical ranking): gains `tech-fde-05`;
  loses `tech-fde-04`, `tech-aieng-02`, `fic-ent-eris`. Top-5 unchanged.
- **z 0.4/0.6**: gains `tech-fde-05`; loses those three plus `tech-aieng-05`.
- **RRF k=60**: gains `tech-fde-05`, `tech-aieng-01`; loses `tech-fde-03`,
  `tech-fde-04`, `tech-aieng-02`, `fic-ent-eris`; drops `tech-fde-04` out of
  top-5 entirely (30/35).
- **gemma only**: the only top-5 gain anywhere is `fic-ent-sandor`, given back on
  `tech-fde-04` and `fic-ent-eris`.

The weights are inert: the legs share top-1 on 20 of 35 rows and 61 % of the
five-passage window, so 0.5/0.5 and 0.6/0.4 produce the same ranking, and
leaning further on gemma loses a row. There is no weight that buys nomic's
precision and gemma's depth, because they disagree exactly where one is wrong.

Nomic's mean rank of 5.26 is inflated by three deep misses — `fic-ent-sandor`
32, `fic-scene-white-place` 34, `fic-scene-alec-dead` 69 — which gemma puts at 3,
7 and 21. Round 1 fusion moves them to 10–11, 10–14 and 35–42 without lifting
any into the window. That is the whole of the mean-rank gain.

## Round 2 — fuse against Dims' truncated gemma leg

Dims found the stored gemma vectors do better truncated to 256 dims and
renormalised (21 top-1, 32 top-5, 2.40) though the control there is unkind. Since
that is the strongest gemma leg available without re-embedding, the same fusion
was rerun with it, nomic unchanged. Control: 40 random 256- (and 224-) dimension
subsets of gemma, same rows and query vectors.

| gemma leg | fusion | top-1 | top-5 | mean gold rank |
|---|---|---|---|---|
| 768 | nomic only (reference) | 26 | 31 | 5.26 |
| 768 | z max | 24 | 31 | 3.03 |
| 256 | z max | **26** | **32** | **2.37** |
| 256 | RRF k=60 | 26 | 32 | 2.80 |
| 256 | z 0.5/0.5 | 26 | 31 | 2.94 |
| 256 | z 0.6 n / 0.4 g | 26 | 31 | 3.20 |
| 256 | z 0.4 n / 0.6 g | 24 | 31 | 2.51 |
| 224 | z max | 26 | 32 | 2.37 |
| 224 | RRF k=60 | 26 | 31 | 2.74 |

Fixed-leg reproduction on this numpy path: gemma 768 19/30/3.00, gemma 256
21/32/2.40, gemma 224 22/31/2.74, nomic 26/31/5.26 — identical to round 1, so the
second implementation is not the difference.

`z max` on the 256-d leg versus nomic only: gains top-1 on `tech-aieng-01` and
`fic-scene-gall-fire`; loses top-1 on `tech-aieng-05` and `fic-ent-eris`; gains
`fic-ent-sandor` in top-5 (32 → 5) and loses none; improves
`fic-scene-white-place` 34 → 8, `fic-scene-alec-dead` 69 → 23, `fic-ent-gall-fire`
4 → 1, `fic-ent-dohga` 2 → 1, and leaves `tech-ddia-02` at 9 (RRF k=60 on the
same leg puts it at 3). Net: top-1 tie, +1 top-5, −2.89 mean rank.

## Control: is any of that the truncation, or the fusion?

40 random dimension subsets, nomic leg fixed, same rows and queries:

| fusion | dims | first-dims (top1/top5/mean) | random top-1 mean (max) | random top-5 mean (max) | p(top1 ≥) | p(top5 ≥) | p(mean ≤) |
|---|---|---|---|---|---|---|---|
| z max | 256 | 26 / 32 / 2.37 | 24.82 (27) | 31.15 (32) | 0.25 | 0.15 | **0.000** |
| z max | 224 | 26 / 32 / 2.37 | 24.98 (27) | 31.27 (32) | 0.28 | 0.28 | **0.000** |
| RRF | 256 | 26 / 32 / 2.80 | 23.80 (27) | 30.15 (32) | 0.10 | 0.025 | **0.000** |
| z 0.5/0.5 | 256 | 26 / 31 / 2.94 | 24.02 (28) | 30.95 (32) | 0.10 | 0.88 | 0.025 |

Read it plainly: the 26 top-1 and the 32 top-5 sit inside the random-subset band
(p 0.10–0.28) — they are a property of fusing two correlated views at all, not of
truncating gemma. The mean gold rank is not noise: no random draw of either size
matched 2.37, and that holds for three different fusions. Fusion reliably deepens
the ranking; it does not reliably find more gold at rank 1 or more often in the
window.

Dims' later 1 000-subset dense-only control (random subsets average mean rank
3.995, sd 0.822, first-256 at the 0.2th percentile) says the truncation deepens
the ranking by itself. The two controls together localise the depth gain: the
fusion's 2.37 is essentially the truncated leg's 2.40, and random-subset fusion
lands at 3.59 mean (sd 0.639, best 2.571). So the depth comes from gemma, and
fusing nomic into it neither adds nor removes depth — it only supplies the rank-1
hits. Nothing in these numbers is a fusion effect on accuracy.

## Round 3 — fuse against Granularity's halves leg

Granularity's finer units (each chunk split into two halves, parent scored by its
best half) lift gemma's own top-1 on the 20 rows whose three books carry units.
That is the one remaining candidate for a stronger gemma leg, so the same fusion
was rerun on those 20 rows only, using their saved vectors
(`/tmp/Granularity/units-*.npz`) and the max-unit parent score they use.

| leg / fusion (20 rows) | top-1 | top-5 | mean gold rank |
|---|---|---|---|
| gemma whole | 5 | 16 | 4.10 |
| gemma halves | 9 | 15 | 8.20 |
| nomic (reference) | 12 | 17 | 8.05 |
| z max, gemma whole | 10 | 17 | 4.10 |
| z max, gemma halves | 10 | 17 | 8.50 |
| z 0.4 nomic / 0.6 halves | 11 | 17 | 6.70 |
| z 0.5/0.5 halves | 11 | 17 | 6.75 |

The finer leg doubles gemma's own top-1 (5 → 9) and still leaves fusion below
nomic alone: best 11 against 12, with the same shape of disagreement — the gains
are `tech-aieng-01` and `fic-ent-atofe`, the losses `tech-fde-04`,
`tech-aieng-02`, `fic-ent-ruijerd`. Mean rank is not comparable across legs here: the
`n_chunks + 1` miss penalty is fair between configurations that share a parent
set, but max-pooling shifts the whole score distribution, so 8.20 against 4.10 is
not like-for-like ordering quality. Granularity scores that leg with mean hit
rank on found rows and mean rank capped at 6 instead. The top-1 and top-5 columns
are hit counts and are the comparable part. What transfers
is the top-1 verdict, and it is the same one as rounds 1 and 2: a better gemma
leg does not make fusion beat nomic.

Granularity then extended unit vectors to the other three books, so the same
fusion was rerun on all 35 answerable rows (91 s of embedding on their side, no
new queries here):

| leg / fusion (35 rows) | top-1 | top-5 | mean gold rank |
|---|---|---|---|
| gemma whole | 19 | 30 | 3.00 |
| gemma halves | 21 | 30 | 5.20 |
| nomic (reference) | 26 | 31 | 5.26 |
| z max, gemma whole | 24 | 31 | 3.03 |
| z max, gemma halves | 24 | 32 | 5.40 |
| z 0.4 nomic / 0.6 halves | **25** | **32** | **4.31** |
| z 0.5/0.5 halves | 25 | 32 | 4.34 |
| z 0.6 nomic / 0.4 halves | 24 | 31 | 4.54 |

The best halves fusion is 25/32/4.31 against nomic's 26/31/5.26: one top-1 short,
one top-5 up (`tech-ddia-02` 9 → 3), gaining `tech-aieng-01` and `fic-ent-atofe`
at rank 1 while losing `tech-fde-04`, `tech-aieng-02`, `fic-ent-ruijerd`. Gemma
halves at 21/30 matches Granularity's own dense-only number and `z max` over
whole 768-d gemma reproduces round 1 exactly (24/31/3.03), so the extension is on
the same footing as the earlier rounds. Means are not comparable between the
whole and halves legs for the reason above; the hit counts are.

## Cross-experiment note

Three gemma levers now sit side by side, with the numbers each experiment
measured:

| lever | top-1 | top-5 | depth |
|---|---|---|---|
| DocFormat, six document formats | no reliable change | unchanged or −1 | no change |
| Granularity, halves over 35 rows | +2 (CI −3…+8) | unchanged | not comparable: pooling shifts the score distribution (sentences lose 4 top-5) |
| Dims, truncate 256 + renormalise | +2 (p 0.23) | +2 (p 0.025, post-hoc) | 3.00 → 2.40, p 0.003 vs 1 000 random subsets |

The shared fact is narrower than "changing the pool helps": gemma's ranking is a
near-tie pool, and label formatting, grain and dimension all reshuffle which
near-tied chunk wins — only the dimension lever changes depth in place. Halves
even move the same row DocFormat's formats move (`tech-fde-04` 12 → 2) and move a
novel row the wrong way (4 → 17). That explains this experiment's shape: the
fusion's top-1 sits inside the random-subset band because it inherits a fragile
ordering at the very top, while its depth gain is robust because depth is read
further down the same ranking. RRF k=60 is the fusion that ignores gemma's score
magnitudes entirely, and it did worse (24/30 at 768-d, 26/32 at 256-d), so
reformatting the gemma leg is not a route past the ceiling either.

Attribution, since three reports touch this: the depth finding is Dims' (the
truncated leg, 3.00 → 2.40) and this experiment's (the same effect appearing
again once nomic is fused in). DocFormat's arm contributes the label result and
declares mean rank tail-sensitive on its data, so its table row carries no depth
claim.

## Verdict

**Nothing beats nomic-only on top-1.** The ceiling across every configuration is
26/35, a tie — and round 3 repeats it with a finer gemma leg: 11 top-1 against
nomic's 12 on the 20 rows that first had unit vectors, and 25 against 26 once all
35 rows did. The finer the gemma leg, the closer the fusion gets to nomic, never
past it. The best 35-row configuration (`z max` over nomic-768 + gemma-256, or
over gemma-224) buys +1 top-5 (32 vs 31, one fiction row, p = 0.15 against random
subsets) and −2.89 mean gold rank (5.26 → 2.37, p = 0.000). Gemma's window
advantage does not transfer to this probe: on these 35 rows gemma's own top-5 is
*worse* than nomic's (30 vs 31, 32 when truncated).

What the dual leg does buy is the union of the two legs' strengths: nomic alone is
26 top-1 but mean rank 5.26, gemma-256 alone is 21 top-1 but mean rank 2.40, and
the fusion is 26 / 32 / 2.37. No single leg holds both halves — but the depth
half is the gemma leg's own, not a fusion effect (see the controls), and the
window half is one fiction row.

The second leg is not worth its latency. Both models are resident and 100 % GPU
(`ollama ps`), yet an uncached single query costs a median 2 233 ms through gemma
against 43 ms through nomic — the gemma mlx runner pays a fixed ~2.1 s per
request regardless of batch size (35 texts in one call: 3.2 s). So a dual leg
means ~50× the query-embedding latency, a second resident model and a doubled
index, in exchange for reordering the same five passages.

If any of this is worth revisiting, it is the 256-d truncation for storage (3×
smaller index, +2 top-5 alone, per Dims), not the second embedder. A cheaper way
to get the depth gain would be reranking nomic's top-k with the gemma vector
already in hand — untested here, and outside this ticket.

Raw per-row ranks, per-config top-5 lists, the truncated-leg tables, the
random-subset control and the halves round: `DualFusion.json`. Scripts:
`/tmp/DualFusion/dual_fusion.py`, `fusion_trunc.py`, `robust.py`,
`halves_fusion.py`. Batch embed time round 1: gemma 3.73 s, nomic
0.66 s for 35 queries; round 2: 3.5–4.8 s for both batches. Ollama was shared
with the three other experiments, so absolute times are contended; the gemma
per-request overhead is stable across runs and is the number that matters.
