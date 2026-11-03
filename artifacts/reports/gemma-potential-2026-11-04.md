# Can gemma be made better? Four experiments — 2026-11-04

Owner question: the top-1 result looked broken; maybe gemma is better and we have
not found the setting that suits it. Four workers tested the settings in parallel
in this worktree (`test-gemma-embedder`), on one fixed measurement set.

## The measurement set

The 42-row authored scoreboard (`artifacts/datasets/retrieval/retrieval-recall-2026-11-02.jsonl`),
35 answerable rows, six books, dense only, k=5. Every experiment reproduced the
baseline before testing anything: gemma **19 top-1 / 30 top-5**, nomic **26 / 31**.

## Why the strict number overstates the gap

`retrieval-support.py` scores a hit three ways: the hand-picked gold chunk
(`exact`), a neighbour (position ±1 in the same source, `neighbour`), or any chunk
that contains the row's `key_fact`.

| embedder | exact@1 | support@1 | support@5 |
|---|---|---|---|
| gemma | 19/35 (54.3 %) | 24/35 (68.6 %) | 32/35 (91.4 %) |
| nomic | 26/35 (74.3 %) | 27/35 (77.1 %) | 32/35 (91.4 %) |

Five of gemma's nine "losses" are the neighbouring chunk; one is a different page
that lists the same five data-engineering stages. At top-5 the two are identical.

Remove the five fiction entity questions, which `entity.py` answers before
retrieval runs, and the served path is **identical**: support@1 23/29 and
support@5 26/29 for both embedders.

## The four levers

| experiment | best configuration | top-1 | top-5 | verdict |
|---|---|---|---|---|
| document format (fde, 1042 chunks × 6 formats; widened to 34 questions) | today's `title: H \| text: body` is unbeaten; raw text, `title:none`, heading-in-both all within noise | 18/34 | 27/34 | no lever. Formats reshuffle the shown five (Jaccard 0.45–0.57) without changing top-1; the heading contributes nothing (dropping it: same top-1, worse mean rank) |
| Matryoshka / centring (no re-embed) | 256-d truncation | 21/35 | 32/35 | the tightest cheap lever, not a proven win: +2 top-1 and +2 top-5, both CI 0…+5 (includes zero). Robust: mean gold rank 2.40 vs 3.00 (p=0.003, 3/1000 random subsets reach it) — ordering depth and 3× less storage, not accuracy |
| finer retrieval units (halves, sentences; 35 rows) | halves | 21/35 | 30/35 | reshuffles, does not repair: +2 top-1 (CI −3…+8), top-5 flat, 2× index; sentences 5.9 units/chunk and lose top-5. Halves at 256-d reach 23 top-1, +2 over whole-256 at CI −5…+9 — not distinguishable, for double the vectors |
| dual embedder (gemma + nomic, 8 fusions, 3 rounds incl. a halves leg) | z-max, nomic-768 + gemma-256 | 26/35 | 32/35 | ties nomic, never beats it; +1 top-5 is one fiction row (p=0.15); depth gain owned by the gemma leg, not by fusing |

Cost, measured five times each, uncached, same box: gemma **2 238 ms** per query
embedding, nomic **563 ms** (one worker measured 43 ms warm). The gemma mlx
runner pays a fixed ~2.1 s per request even resident. A dual leg is 4–50× the
query cost for a reorder of the same five passages.

## What this says

Gemma's ranking is a near-tie pool, and neither the label nor the grain moves it
reliably: six document formats reshuffle the shown five without changing top-1,
and halves are +2 top-1 with a CI of −3…+8 and no top-5 change. Both move the same
row (`tech-fde-04`, rank 12 → 2) and both move a novel row the wrong way, so
format is the free version of the same reshuffle. The one lever that behaves
differently is truncation: it sharpens depth in place and keeps 32/35 top-5. Its real advantage is window coverage — 86.5 % vs 81.8 % over the
170-question set in `artifacts/reports/embeddinggemma2-vs-nomic-2026-11-04.md` —
and its real cost is per-query latency.

Recommendation: do not switch the default. Nomic is equal on the served path,
better on exact rank-1, and 4–50× cheaper to query. Keep gemma installed for the
wide-net coverage experiments. If storage ever matters, 256-d truncation is the
one measured free lever — +2 top-1 / +2 top-5 at CI 0…+5, and 3× less storage —
but the interval includes zero, so it belongs to a storage decision, not an
accuracy claim.

## Evidence on disk, in this worktree

- `artifacts/experiments/gemma/PROTOCOL.md` — the fixed measurement rules.
- `DocFormat.{json,md}`, `Dims.{json,md}`, `Granularity.{json,md}`, `DualFusion.{json,md}`
  — per-row ranks, controls, bootstrap intervals, and the scripts' locations.
- `artifacts/harnesses/retrieval-support.py` + `support-{gemma,nomic}.json` — the
  exact / neighbour / key_fact scoring used above.
