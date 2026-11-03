# Granularity — are 1400-char chunks too coarse for gemma?

**Answer: no, not in any way that pays for itself.** Splitting the same chunks into
halves recovers exact-chunk top-1 on technical books and destroys window recall in
the novel; sentence-level units lose more than they win and cost six times the
index. Across all 35 answerable rows halves net +2 top-1 and 0 top-5 for double the
index — a reshuffle, not a repair. Details and numbers below.

## What was measured

20 answerable rows on the three books that hold 15 of gemma's 16 whole-chunk top-1
misses: `index` (fde) 5 rows, `index.ai-engineering` 5, `index.mushoku-tensei-...` 10.
Whole-chunk baseline re-derived first on all 35 answerable rows — **19/35 top-1,
30/35 top-5** — exactly the protocol number, so the subset is scored by the same
rule as everyone else.

Two finer views of the *existing* indexes, nothing written to `data/`:

- **halves** — the chunk body is cut at the sentence boundary (`. ! ?` + whitespace)
  nearest the character midpoint. 2053 / 2044 / 547 units for 1042 / 1030 / 274
  chunks; the 48 chunks with no usable midpoint boundary stay one unit.
- **sentences** — `answer._sentences(body)`, keep every sentence with **12+ words**,
  accumulate in order while the total stays within the parent's own character
  budget. That budget never bit (0 sentences dropped, the sentences are substrings);
  the effective filter is the 12-word rule. 5867 / 6295 / 1654 units. The 39 chunks
  with no qualifying sentence fall back to the whole body.

Every unit carries its parent `chunk_id`. Documents are embedded with
`retrieve.format_input(model, "document", unit_text, heading)` — the engine's exact
`title: <heading> | text: <unit>` form — and queries with its `task: search result |`
prefix, so this is a granularity change only. A parent's score is the **max** of its
units' cosines; parents are ranked by that score and the metrics are at parent
level. Cosine itself, not a re-ranker.

## Results

Mean rank is capped at 6 (a miss in a 1042-chunk book would otherwise contribute
1042 and swamp the average); uncapped values are in the JSON. "Mean hit rank" is
the average rank when the row is a top-5 hit.

| units | book | top-1 | top-5 | mean rank (≤6) | mean hit rank |
|---|---|---|---|---|---|
| whole | fde (5) | 2 | 4 | 2.4 | 1.5 |
| whole | ai-engineering (5) | 3 | 5 | 1.4 | 1.4 |
| whole | novel (10) | 0 | 7 | 3.7 | 2.71 |
| **whole** | **all 20** | **5** | **16** | **2.8** | **2.0** |
| halves | fde | 3 | 5 | 1.4 | 1.4 |
| halves | ai-engineering | 4 | 5 | 1.2 | 1.2 |
| halves | novel | 2 | 5 | 4.3 | 2.6 |
| **halves** | **all 20** | **9** | **15** | **2.8** | **1.73** |
| sentences | fde | 3 | 5 | 1.6 | 1.6 |
| sentences | ai-engineering | 3 | 5 | 1.8 | 1.8 |
| sentences | novel | 2 | 2 | 5.0 | 1.0 |
| **sentences** | **all 20** | **8** | **12** | **3.35** | **1.58** |

Paired bootstrap over the 20 rows, 10 000 draws, delta vs whole chunks:

| config | Δ top-1 (95 % CI) | Δ top-5 (95 % CI) |
|---|---|---|
| halves | +3.97 (0 … +9) | −1.02 (−4 … +2) |
| sentences | +3.00 (−2 … +8) | −4.01 (−9 … 0) |

Halves' top-1 gain is real in count (+4 net on 20 rows) but its interval touches
zero. Sentences' top-5 loss is the one interval that excludes zero.

## What actually moves

Halves, per row: fixed `tech-fde-02` (2→1), `tech-fde-03` (2→1), `tech-aieng-05`
(2→1), `fic-ent-atofe` (2→1), `fic-scene-badigadi` (2→1); broke `tech-fde-05`
(1→2). Sentences fixed `tech-fde-03`, `tech-fde-04` (12→1), `tech-aieng-02`,
`fic-ent-atofe`, `fic-scene-badigadi`; broke `tech-fde-05` and `tech-aieng-01`
(1→4).

On this twenty-row subset the technical gain is real and legible: `tech-fde-04`
(Kinesis Firehose) goes from rank 12 to 2 with halves and **1** with sentences,
because the answer sentence is one fact inside a long chunk that the whole-chunk
vector dilutes. The fiction regression is equally legible: the novel's gold chunks are character dossiers, and
`who is sandor` regresses from rank 4 to 17. Sandor's gold halves score 0.65 / 0.73
/ 0.71, essentially the same as the parent chunks, but fragments elsewhere that
merely *name* him (`"Sandor, or the North God Kalman II, who was more f..."`) score
0.77 and rise. A shorter unit is a weaker binding of a name to a role, and the
novel has dozens of name-drops per entity.

Two checks rule out the obvious artefacts:

- **Length bias:** per-query Pearson r between unit length and cosine is
  0.00–0.14 (not negative) for halves and sentences in all three books, and the
  winning unit is not short relative to the pool. Short units are not winning by
  inflated similarity.
- **Aggregation:** re-ranking with the *mean* of a parent's units instead of the max
  is worse everywhere (novel halves 2/5 → 0/3 top-1/top-5, sentences 2/2 → 0/1).
  Max is the right rule, so sentences lose because a fragment matches, not because
  pooling gives the six-unit parents extra draws.

On the neighbour-chunk question this experiment opens: 4 of the 15 whole-chunk
top-1 misses in these books are a literal ±1 chunk (`fde-04`, `aieng-02`,
`aieng-05`, `gall-fire`). Halves fix exactly one of them to top-1 (`aieng-05`);
sentences fix two (`fde-04`, `aieng-02`). So the "neighbouring chunk" story is
confirmed as a real grain problem on technical prose, but finer units do not
resolve it in general — the ranking just reshuffles the same parents.

## Extension — halves on the other three books, and all 35 rows

To test whether the technical gain is general or two-book luck, halves were also
built for `index.quantization` (473 chunks), `index.ddia` (1306) and
`index.ai-agents` (637): 4681 units in 91 s. Sentences were not extended — they are
already ruled out by top-5 and cost.

| book | rows | halves top-1 / top-5 | whole top-1 / top-5 |
|---|---|---|---|
| fde | 5 | 3 / 5 | 2 / 4 |
| ai-engineering | 5 | 4 / 5 | 3 / 5 |
| novel | 10 | 2 / 5 | 0 / 7 |
| quantization | 5 | 4 / 5 | 5 / 5 |
| ddia | 5 | 4 / 5 | 4 / 4 |
| ai-agents | 5 | 4 / 5 | 5 / 5 |
| **all 35** | **35** | **21 / 30** | **19 / 30** |

Bootstrap over 35 rows: Δtop-1 +2.02 (95 % CI −3 … +8), Δtop-5 0.00 (−4 … +4).

The effect is a reshuffle, not a repair. Halves help where the whole chunk buries
the answer (`fde-04` 12→2, `ddia-02` 9→2, `fde-02` 2→1, `fde-03` 2→1,
`aieng-05` 2→1) and hurt where gemma already gets it right (`quant-05` 1→2,
`aiagents-04` 1→2) or where the chunk is an entity dossier (the novel's
sandor 4→17, rudeus 4→20, white-place 7→33, alec 21→62). Net: +2 top-1, no change
in top-5, for double the index.

## Interaction with 256-d truncation

Dims' truncation result prompted a free cross-check: the saved unit vectors were
prefix-truncated to 256 dims and re-ranked, no re-embedding.

| config | 768-d | 256-d |
|---|---|---|
| whole | 19 / 30 | 18 / 31 |
| halves | 21 / 30 | 19 / 31 |
| sentences (20 rows only) | 8 / 12 | 8 / 13 |

Finer units and truncation do not fight each other, but they do not add up either:
halves+256 is 19 top-1 / 31 top-5 of 35 at 4.76 MB of vectors, versus whole-768 at
19/30 and 7.2 MB. That is the cheapest arm anyone in this round has produced, and
it is still a one-row difference.

## Cost

Measured on the three books (2346 chunks), Ollama shared with three other
experiments: halves 4644 units embedded in 164 s, sentences 13 816 units in 416 s
(35 / 30 ms per unit under contention; 24 ms for a quiet 64-text batch before the
others ramped up). Wall clock 9 m 44 s for that run; the extension's 4681 halves on
the other three books took 91 s. All-35 projection is therefore ≈ 9.3 k halves
units, ≈ 29 MB of vectors, ≈ 4.3 min on a contended box.

| | units | units/parent | vectors (768-d fp32) | text chars |
|---|---|---|---|---|
| whole | 2346 | 1.00 | 7.2 MB | 2.37 M |
| halves | 4644 | 1.98 | 14.3 MB | 2.28 M |
| sentences | 13 816 | 5.89 | 42.4 MB | 1.72 M |

Projected to the full six-book corpus (4762 chunks): halves ≈ 9.4 k units / 29 MB /
5.5 min of embedding; sentences ≈ 28 k units / 86 MB / 14 min. Query latency is
unchanged (one query embedding); ranking cost is 2× or 6× the dot products, which
is milliseconds at this corpus size.

## Verdict

**Finer units are not worth the index they cost.** Halves double the index and the
embedding time to buy +2 top-1 and 0 top-5 across the full 35 rows (CI −3…+8): they
recover rows where a long chunk buried the answer and lose rows gemma already had,
so the ranking is reshuffled rather than improved. Sentences cost six times the index
and lose top-5 outright (−4, CI −9…0 on the 20-row subset), so they are dead.
Truncation does not change the picture: halves+256 matches whole-768 on top-1 at
two-thirds of the vector size, which is a cost story, not an accuracy one. Nor does
the finer leg lift fusion: DualFusion's Round 3 over these unit vectors reaches
25 top-1 / 32 top-5 on the 35 rows (best halves arm), still one top-1 short of
nomic alone (26/31).

If the lead wants to spend anything here, the only defensible move is the one the
data supports at low risk: truncate the stored vectors to 256 dims (Dims: +2 top-1,
+2 top-5, −0.6 mean rank on 35 rows, and it is free), and treat max-pooled halves as
a per-book lever only for books whose exact-chunk top-1 is already the worst
(fde/ai-engineering), never for the novel, where window recall is the thing the
embedder was hired for. Do not switch granularity globally on this evidence.

